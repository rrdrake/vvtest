#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import sys
sys.dont_write_bytecode = True
sys.excepthook = sys.__excepthook__
import os
import time
import re
import shutil
import hashlib
import fnmatch
import stat

import pythonproxy as rpy

import perms


helpstr = \
"""
USAGE:
    filesync.py [OPTIONS] [machine:]from_dir [machine:]to_dir

SYNOPSIS:
    Copy or overwrite files in the 'from_dir' directory to the 'to_dir'
    directory.  At most one directory can be prefixed with a machine name.
    All files in 'from_dir' are copied by default.

    File operations are performed using the remotepython module (over ssh),
    so the only requirement on the remote machine is that a python (of any
    version) be in PATH.

OPTIONS:
    -h, --help             : this help
    -g <pattern>           : glob pattern of files to copy; may be repeated
    --age <seconds old>    : only files newer than this age are copied
    -T <seconds>           : apply timeout to each remotepython command
    --sshexe <path to ssh> : use this ssh
    --perms <spec>         : set or adjust file permissions on files placed
                             into the target location; may be repeated, and
                             separate multiple specs with whitespace;
                             examples:
                                groupname : set the file group name
                                o=-     : set world permissions to none
                                g=r-x   : set group to read, no write, execute
                                g+rX    : add read & conditional execute to group
                                o-w     : remove write to world
                                u+x     : add execute to owner
"""

############################################################################

def main():

    import getopt
    optL,argL = getopt.getopt( sys.argv[1:], 'hg:T:',
                               longopts=['help','age=','sshexe=','perms='] )

    optD ={}
    for n,v in optL:
        if n == '-h' or n == '--help':
            print3( helpstr )
            return 0
        elif n in ['-g']:
            optD[n] = optD.get(n,[]) + [v]
        elif n == '--perms':
            optD[n] = optD.get(n,[]) + v.split()
        else:
            optD[n] = v

    if len(argL) != 2:
        print3( '*** filesync.py: expected exactly two arguments' )
        sys.exit(1)

    age = optD.get( '--age', None )
    if age != None:
        age = float( age )

    tmout = optD.get( '-T', None )
    if tmout != None:
        tmout = float( tmout )

    sync_directories( argL[0], argL[1],
                      glob=optD.get( '-g', '*' ),
                      age=age,
                      timeout=tmout,
                      sshexe=optD.get( '--sshexe', None ),
                      permissions=optD.get( '--perms', [] ) )


############################################################################

def sync_directories( read_dir, write_dir, glob='*', age=None,
                      echo=True, timeout=None, sshexe=None, permissions=[] ):
    """
    Copy or overwrite files from 'read_dir' into 'write_dir'.  Only files
    that match the 'glob' pattern and are no older than 'age' seconds are
    copied (no age limit by default).

    Either the read dir or write dir can be prefixed with a machine name
    plus a colon to indicate a directory on a remote machine.  For example,
    "sparky:/some/directory" means the directory /some/directory on machine
    sparky.  A machine specification can only be given to one directory,
    not both.

    The 'glob' argument can be a shell glob pattern or a python list of
    patterns.

    If 'echo' is True, the actions are printed to stdout as they occur.

    If 'timeout' is not None, a time limit is applied to each remote operation,
    and if one times out, an exception is raised.

    The 'sshexe' option is passed through to the RemotePython constructor.
    """
    rm,rd = splitmach( read_dir )
    wm,wd = splitmach( write_dir )

    assert rm == None or wm == None, "two remote paths not supported"

    rmt = None

    # list source files
    if rm == None:
        rL = long_list_files( rd, glob=glob, age=age )
    else:
        rmt = create_remote_proxy( rm, sshexe, timeout, echo )
        rL = rmt.call( 'long_list_files', rd, glob=glob, age=age )

    # list target files
    if wm == None:
        wL = long_list_files( wd, glob=glob, age=age )
    else:
        rmt = create_remote_proxy( wm, sshexe, timeout, echo )
        wL = rmt.call( 'long_list_files', wd, glob=glob, age=age )

    try:
        wD = {}
        for T in wL:
            wD[ T[0] ] = T

        # compose list of files which need to be copied
        cpL = []
        for rT in rL:
            wT = wD.get( rT[0], None )
            if wT == None or abs( rT[1]-wT[1] ) > 1 or \
                             rT[2] != wT[2] or \
                             rT[3] != wT[3]:
                f = rT[0]
                cpL.append( (f, rd+'/'+f, wd+'/'+f) )

        if rm == None and wm == None:
            # copy files local to local
            for f,rf,wf in cpL:
                if echo: print3( 'copy -p '+rf+' '+wf )
                shutil.copy2( rf, wf )
                if permissions:
                    file_perms( wf, permissions )

        elif rm != None:
            # copy files from remote machine to local
            for f,rf,wf in cpL:
                if echo: print3( 'copy -p '+read_dir+'/'+f+' '+wf )
                if timeout: rmt.setRemoteTimeout(timeout)
                recv_file( rmt, rf, wf )
                if permissions:
                    file_perms( wf, permissions )

        else:
            assert wm != None
            # copy files from local to remote machine
            for f,rf,wf in cpL:
                if echo: print3( 'copy -p '+rf+' '+write_dir+'/'+f )
                if timeout: rmt.setRemoteTimeout(timeout)
                send_file( rmt, rf, wf )
                if permissions:
                    file_perms( wf, permissions, remote=rmt )

    finally:
        if rmt != None:
            if timeout: rmt.setRemoteTimeout(timeout)
            rmt.close()

    return [ T[0] for T in cpL ]


def create_remote_proxy( mach, sshexe, timeout, echo ):
    ""
    rmt = rpy.RemotePythonProxy( mach, sshcmd=sshexe )

    if echo:
        print3( 'Connecting to "'+mach+'"' )
    rmt.start()

    rmt.execute( 'import glob',
                 'import stat',
                 'import shutil',
                 'import time',
                 'import hashlib',
                 'import fnmatch' )
    rmt.send( perms,
              list_files,
              long_list_files,
              get_file_stats,
              set_file_stats,
              readfile,
              filesha1,
              print3 )
    rmt.execute( 'import perms' )

    if timeout:
        rmt.setRemoteTimeout(timeout)

    return rmt


def file_perms( fname, permissions, remote=None ):
    """
    Sets file permissions on file 'fname' given a python list of (string)
    specifications. If 'remote' is not None, it must be a connected
    RemotePython instance, which is used to perform the operations on the
    remote machine.  The permissions are only changed if the user of this
    process and the user of the file are the same.
    """
    if remote == None:
        if perms.i_own( fname ):
            if type(permissions) == type(''):
                perms.apply_chmod( fname, permissions )
            else:
                # assume 'permissions' is a tuple or list
                perms.apply_chmod( fname, *permissions )
    else:
        if remote.call( 'perms.i_own', fname ):
            if type(permissions) == type(''):
                remote.call( 'perms.apply_chmod', fname, permissions )
            else:
                # assume 'permissions' is a tuple or list
                remote.call( 'perms.apply_chmod', fname, *permissions )


_machine_prefix_pat = re.compile( '[0-9a-zA-Z_.-]+?:' )

def splitmach( path ):
    """
    Separates "machine:directory" into a pair (machine, directory).  If a
    machine is not specified, returns (None, directory).
    """
    m = _machine_prefix_pat.match( path )
    if m == None:
        return None,path
    return path[:m.end()-1], path[m.end():]


def send_file( rmt, rf, wf ):
    ""
    stats = get_file_stats( rf )
    rfp = rmt.construct( 'open', wf, 'wt' )
    rfp.write( readfile( rf ) )
    rfp.close()
    rmt.call( 'set_file_stats', wf, stats )


def recv_file( rmt, rf, wf ):
    ""
    stats = rmt.call( 'get_file_stats', rf )
    fp = open( wf, 'wt' )
    fp.write( rmt.call( 'readfile', rf ) )
    fp.close()
    set_file_stats( wf, stats )


def list_files( directory, glob='*', age=None ):
    "Returns a list of files matching the given pattern no older than 'age'."
    # glob can be a string or a list of strings
    if type(glob) == type(''):
        glob = [glob]

    L = []
    for f in os.listdir( directory ):
        for pat in glob:
            if fnmatch.fnmatch( f, pat ):
                L.append(f)
                break

    if age == None:
        return L

    tm = time.time()
    fL = []
    for f in L:
        mt = os.path.getmtime( directory+'/'+f )
        if tm-mt <= age:
            fL.append(f)

    return fL


def long_list_files( directory, glob='*', age=None ):
    "Same as list_files() except each entry is (filename, modification time, file size, SHA-1)."
    L = list_files( directory, glob, age )
    fL = []
    for f in L:
        df = directory+'/'+f
        fL.append( ( f, os.path.getmtime(df), os.path.getsize(df), filesha1(df) ) )
    return fL


def get_file_stats( filename ):
    ""
    mtime = os.path.getmtime( filename )
    atime = os.path.getatime( filename )
    fmode = stat.S_IMODE( os.stat(filename)[stat.ST_MODE] )
    return mtime,atime,fmode


def set_file_stats( filename, stats ):
    ""
    mtime,atime,fmode = stats
    os.utime( filename, (atime,mtime) )
    os.chmod( filename, fmode )


def readfile( filename ):
    ""
    with open( filename, 'rt' ) as fp:
        content = fp.read()

    return content


def filesha1( filename ):
    """
    Returns the SHA-1 hex digest of the contents of the given filename
    """
    dig = hashlib.sha1()
    fp = open( filename )
    try:
        if sys.version_info[0] < 3:
            dig.update( fp.read() )
        else:
            dig.update( fp.read().encode() )
    finally:
        fp.close()

    return dig.hexdigest()


def print3( *args ):
    sys.stdout.write( ' '.join( [ str(x) for x in args ] ) + os.linesep )
    sys.stdout.flush()


##########################################################################

if __name__ == "__main__":
    mydir = os.path.abspath( sys.path[0] )
    main()
