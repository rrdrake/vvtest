#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import sys
sys.dont_write_bytecode = True
sys.excepthook = sys.__excepthook__
import os
import shutil
import tempfile
import string
import random
from os.path import join as pjoin
from os.path import abspath, normpath, realpath, dirname
import pipes
import subprocess

import perms


class FileUtilsError( Exception ):
    pass


def send_path( srcpath, destpath, proxy=None, permissions='' ):
    """
    Send 'srcpath' (a file or directory) to, and replace, 'destpath'.
    If 'proxy' is not None, it must be a PythonProxy instance and applies to
    the destination path.
    If 'permissions' is not empty, it must be group and/or file mode
    specifications, such as "wg-my-group,g+rX,o=", and applies to 'destpath'.
    """
    if proxy == None or not proxy.get_machine_name():
        local_path_copy( srcpath, destpath, permissions )
    else:
        send_to_remote( srcpath, destpath, proxy, permissions )


def recv_path( destpath, srcpath, proxy=None, permissions='' ):
    """
    Receive 'srcpath' (a file or directory) and replace 'destpath'.
    If 'proxy' is not None, it must be a PythonProxy instance and applies
    to the source path.
    If 'permissions' is not empty, it must be group and/or file mode
    specifications, such as "wg-my-group,g+rX,o=", and applies to 'destpath'.
    """
    if proxy == None or not proxy.get_machine_name():
        local_path_copy( srcpath, destpath, permissions )
    else:
        recv_from_remote( destpath, srcpath, proxy, permissions )


def is_subpath( path, subpath ):
    """
    Returns True if 'subpath' is in a subdirectory of 'path' or is the same
    as 'path' as they exist on the file system (soft links are resolved).
    """
    p1 = realpath( path )
    p2 = realpath( subpath )
    return p1 == p2 or ( p2.startswith( p1 ) and p2[len(p1)] == os.path.sep )


########################################################################

def local_path_copy( srcpath, destpath, permissions ):
    ""
    check_copy_tree_subpath( srcpath, destpath )

    # magic: check that srcpath exists
    # magic: check that destdir exists

    srcdir,srcfname = split_sourcepath( srcpath )
    destdir,filename = split_destination( destpath )

    tmpdir = tempfile.mkdtemp( suffix='', prefix='tmpdir_', dir=destdir )
    try:
        tmppath = pjoin( tmpdir, srcfname )
        copy_into_directory( srcdir, srcfname, tmpdir )
        swap_replace_path( tmppath, destpath, tmpdir, permissions )
    finally:
        shutil.rmtree( tmpdir )


def split_sourcepath( srcpath ):
    ""
    return os.path.split( os.path.realpath( srcpath ) )


def split_destination( destpath ):
    ""
    return os.path.split( normpath( abspath( destpath ) ) )


def copy_into_directory( srcdir, srcfname, destdir ):
    ""
    srcloc = pjoin( srcdir, srcfname )
    tmploc = pjoin( destdir, srcfname )

    if os.path.isfile( srcloc ):
        shutil.copy2( srcloc, tmploc )
    else:
        shutil.copytree( srcloc, tmploc, symlinks=True )


def send_to_remote( srcpath, destpath, proxy, permissions ):
    ""
    fu,su,tf,pm = check_load_modules( proxy )

    srcdir,srcfname = split_sourcepath( srcpath )
    destdir,filename = fu.split_destination( destpath )

    tmpdir = tf.mkdtemp( suffix='', prefix='tmpdir_', dir=destdir )
    try:
        tmppath = pjoin( tmpdir, srcfname )
        send_path_to_remote( proxy, srcdir, srcfname, tmpdir )
        fu.swap_replace_path( tmppath, destpath, tmpdir, permissions )
    finally:
        su.rmtree( tmpdir )


def recv_from_remote( destpath, srcpath, proxy, permissions ):
    ""
    fu,su,tf,pm = check_load_modules( proxy )

    srcdir,srcfname = fu.split_sourcepath( srcpath )
    destdir,filename = split_destination( destpath )

    tmpdir = tempfile.mkdtemp( suffix='', prefix='tmpdir_', dir=destdir )
    try:
        tmppath = pjoin( tmpdir, srcfname )
        recv_path_from_remote( proxy, srcdir, srcfname, tmpdir )
        swap_replace_path( tmppath, destpath, tmpdir, permissions )
    finally:
        shutil.rmtree( tmpdir )


def check_load_modules( proxy ):
    ""
    proxy.send( modules_available )

    if not proxy.modules_available():
        proxy.send( perms, sys.modules['fileutils'] )

    fu = proxy.import_module( 'fileutils' )
    su = proxy.import_module( 'shutil' )
    tf = proxy.import_module( 'tempfile' )
    pm = proxy.import_module( 'perms' )

    return fu,su,tf,pm


def modules_available():
    return 'fileutils' in sys.modules and 'perms' in sys.modules


def send_path_to_remote( proxy, srcdir, srcfname, destdir ):
    ""
    sshcmd = proxy.get_ssh_command() + ' ' + proxy.get_machine_name()
    pack = 'tar -C '+pipes.quote(srcdir)+' -c ' + pipes.quote(srcfname)
    unpack = sshcmd + ' ' + \
             pipes.quote( 'tar -C '+pipes.quote(destdir)+' -xpf -' )
    shcmd( pack + ' | ' + unpack )


def recv_path_from_remote( proxy, srcdir, srcfname, destdir ):
    ""
    sshcmd = proxy.get_ssh_command() + ' ' + proxy.get_machine_name()
    pack = sshcmd + ' tar -C '+pipes.quote(srcdir)+' -c ' + pipes.quote(srcfname)
    unpack = 'tar -C '+pipes.quote(destdir)+' -xpf -'
    shcmd( pack + ' | ' + unpack )


def shcmd( cmd ):
    ""
    print ( cmd )

    pop = subprocess.Popen( cmd, shell=True, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE )
    out,err = pop.communicate()

    if pop.returncode != 0:
        if out:
            if sys.version_info[0] > 2: out = out.decode()
            sys.stdout.write(out)
            sys.stdout.flush()
        if err:
            if sys.version_info[0] > 2: err = err.decode()
            sys.stderr.write(err)
            sys.stdout.flush()

        raise FileUtilsError( 'shell command failed: '+cmd )


def swap_replace_path( srcpath, destpath, tmpdir, permissions ):
    """
    Permissions are applied to 'srcpath' prior to swap.
    If 'destpath' does not exist or is a soft link, then this renames 'srcpath'
    to 'destpath'. If 'destpath' exists, the two paths are swapped (that is,
    their contents and permissions are swapped).
    """
    if permissions:
        perms.apply( srcpath, permissions, recurse=True )

    if os.path.islink( destpath ):
        os.remove( destpath )
        os.rename( srcpath, destpath )
    elif os.path.exists( destpath ):
        swap_paths( srcpath, destpath, tmpdir )
    else:
        os.rename( srcpath, destpath )


def swap_paths( path1, path2, tmpdir ):
    ""
    tmp = pjoin( tmpdir, random_string() )

    os.rename( path1, tmp )
    os.rename( path2, path1 )
    os.rename( tmp, path2 )


def random_string( numchars=10 ):
    ""
    seq = string.ascii_letters + string.digits
    cL = [ random.choice( seq ) for _ in range(numchars) ]
    return ''.join( cL )


def check_copy_tree_subpath( srcpath, destpath ):
    ""
    sub = False

    if os.path.islink( destpath ):
        tmp = pjoin( dirname( destpath ), random_string() )
        if is_subpath( srcpath, tmp ) or is_subpath( tmp, srcpath ):
            sub = True
    elif is_subpath( srcpath, destpath ) or is_subpath( destpath, srcpath ):
        sub = True

    if sub:
        raise FileUtilsError(
            "'srcpath' cannot be a parent nor subdirectory of 'destpath': "
            "srcpath="+repr(srcpath)+", destpath="+repr(destpath) )
