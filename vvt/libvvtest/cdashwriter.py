#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time
from os.path import join as pjoin
from os.path import basename
import stat

from . import outpututils
print3 = outpututils.print3


class CDashWriter:

    def __init__(self, destination, results_test_dir, permsetter):
        ""
        self.dest = destination
        self.testdir = results_test_dir
        self.permsetter = permsetter

        self.formatter = None
        self.submitter = None

        self.datestamp = None
        self.proj = None

    def setCDashFormatter(self, formatter_type, submitter_type):
        ""
        self.formatter = formatter_type
        self.submitter = submitter_type

    def setResultsDate(self, datestamp):
        ""
        self.datestamp = datestamp

    def setProjectName(self, proj):
        ""
        self.proj = proj

    def prerun(self, atestlist, rtinfo, verbosity):
        ""
        pass

    def midrun(self, atestlist, rtinfo):
        ""
        pass

    def postrun(self, atestlist, rtinfo):
        ""
        fmtr = self._create_and_fill_formatter( atestlist, rtinfo )
        self._write_data( fmtr, rtinfo )

    def info(self, atestlist, rtinfo):
        ""
        fmtr = self._create_and_fill_formatter( atestlist, rtinfo )
        self._write_data( fmtr, rtinfo )

    def _create_and_fill_formatter(self, atestlist, rtinfo):
        ""
        print3( '\nComposing CDash submission data...' )

        fmtr = self.formatter()
        set_global_data( fmtr, self.datestamp, rtinfo )
        set_test_list( fmtr, atestlist, self.testdir )
        return fmtr

    def _write_data(self, fmtr, rtinfo):
        ""
        if is_http_url( self.dest ):

            fname = pjoin( self.testdir, 'vvtest_cdash_submit.xml' )

            try:
                print3( 'Writing CDash submission file:', fname )
                self._write_file( fmtr, fname )

                assert self.proj, 'CDash project name not set'
                sub = self.submitter( self.dest, self.proj )
                print3( 'Sending CDash file to:', self.dest + ',',
                        'project='+self.proj )
                sub.send( fname )

                print3()

            except Exception as e:
                print3( '\n*** WARNING: error submitting CDash results:',
                        str(e), '\n' )

        else:
            print3( 'Writing CDash submission file:', self.dest )
            self._write_file( fmtr, self.dest )
            print3()

    def _write_file(self, fmtr, filename):
        ""
        fmtr.writeToFile( filename )
        self.permsetter.set( filename )


def set_global_data( fmtr, date_stamp, rtinfo ):
    ""
    if date_stamp:
        bdate = date_stamp
        tstart = rtinfo.getInfo( 'startepoch', bdate )
    else:
        bdate = rtinfo.getInfo( 'startepoch', time.time() )
        tstart = bdate

    rdir = rtinfo.getInfo( 'rundir', None )
    if rdir:
        rdir = basename( rdir )

    fmtr.setBuildID( build_date=bdate,
                     site_name=rtinfo.getInfo( 'hostname', None ),
                     build_name=rdir )

    fmtr.setTime( tstart, rtinfo.getInfo( 'finishepoch', None ) )


def set_test_list( fmtr, atestlist, testdir ):
    ""
    tcaseL = atestlist.getActiveTests()

    for tcase in tcaseL:

        tspec = tcase.getSpec()
        tstat = tcase.getStat()

        vvstat = tstat.getResultStatus()

        if vvstat == 'notrun':
            fmtr.addTest( tspec.getDisplayString(),
                          status='notrun' )

        elif vvstat == 'pass':
            fmtr.addTest( tspec.getDisplayString(),
                          status='passed',
                          runtime=tstat.getRuntime( None ),
                          exitvalue=tspec.getAttr( 'xvalue', None ) )

        else:

            file_max_KB = 100
            out = get_test_output( testdir, tspec, file_max_KB )

            fmtr.addTest( tspec.getDisplayString(),
                          status='failed',
                          runtime=tstat.getRuntime( None ),
                          detail=vvstat,
                          output=out,
                          exitvalue=tspec.getAttr( 'xvalue', None ) )


def is_http_url( destination ):
    ""
    if os.path.exists( destination ):
        return False
    elif destination.startswith( 'http://' ) or \
         destination.startswith( 'https://' ):
        return True
    else:
        return False


def get_test_output( testdir, tspec, file_max_KB ):
    ""
    tdir = pjoin( testdir, tspec.getExecuteDirectory() )

    out = '\n'
    out += 'CURTIME : ' + time.ctime() + '\n'
    out += 'HOSTNAME: ' + os.uname()[1] + '\n'
    out += 'TESTDIR : ' + tdir + '\n'

    out += '\n$ ls -l '+tdir+'\n'
    out += '\n'.join( list_directory_as_strings( tdir ) ) + '\n'

    for fn in [ 'execute.log' ]:
        pn = pjoin( tdir, fn )
        if os.path.exists( pn ):
            out += '\n' + get_file_contents( pn, file_max_KB ) + '\n'

    return out


def get_file_contents( filename, max_KB ):
    ""
    out = '$ cat '+filename+'\n'

    try:
        out += outpututils.file_read_with_limit( filename, max_KB )
    except Exception as e:
        out += '*** failed to cat file: '+str(e)

    if not out.endswith( '\n' ):
        out += '\n'

    return out


def list_directory_as_strings( dirpath ):
    ""
    try:
        fL = os.listdir( dirpath )
        fL.append( '.' )
    except Exception as e:
        return [ '*** failed to list directory "'+dirpath+'": '+str(e) ]

    lines = []
    maxlens = [ 0, 0, 0, 0, 0, 0 ]
    for fn,props in list_file_properties( dirpath, fL ):
        lineL = file_properties_as_strings( fn, props, maxlens )
        lines.append( lineL )

    fmtlines = []
    for lineL in lines:
        fmtL = [ lineL[0],
                 ( "%-"+str(maxlens[1])+"s" ) % ( lineL[1], ),
                 ( "%-"+str(maxlens[2])+"s" ) % ( lineL[2], ),
                 ( "%"+str(maxlens[3])+"s" ) % ( lineL[3], ),
                 lineL[4],
                 lineL[5] ]
        fmtlines.append( ' '.join( fmtL ) )

    return fmtlines


def file_properties_as_strings( fname, props, maxlens ):
    ""
    sL = [ props['type'] + props['mode'],
           props['owner'],
           props['group'],
           str( props['size'] ),
           make_string_time( props['mtime'] ) ]

    if props['type'] == 'l':
        sL.append( fname + ' -> ' + props['link'] )
    else:
        sL.append( fname )

    for i in range( len(sL) ):
        maxlens[i] = max( maxlens[i], len(sL[i]) )

    return sL


def make_string_time( secs ):
    ""
    return time.strftime( "%Y/%m/%d %H:%M:%S", time.localtime(secs) )


def list_file_properties( dirpath, fL ):
    ""
    files = []

    for fn in fL:
        pn = pjoin( dirpath, fn )
        props = read_file_properties( pn )
        files.append( [ props.get('mtime'), fn, props ] )

    files.sort()

    return [ L[1:] for L in files ]


def read_file_properties( path ):
    ""
    pwd, grp = get_pwd_and_grp_modules()

    ftype,statvals = get_stat_values( path )

    props = {}
    props['type'] = ftype

    if ftype == 'l':
        props['link'] = read_symlink( path )

    if statvals != None:
        props['mtime'] = statvals[ stat.ST_MTIME ]
        props['size']  = statvals[ stat.ST_SIZE ]
        props['owner'] = get_path_owner( statvals, pwd )
        props['group'] = get_path_group( statvals, grp )
        props['mode']  = make_mode_string( statvals )
    else:
        props['mtime'] = 0
        props['size']  = 0
        props['owner'] = '?'
        props['group'] = '?'
        props['mode']  = '?????????'

    return props


def get_pwd_and_grp_modules():
    ""
    try:
        import pwd
    except Exception:
        pwd = None

    try:
        import grp
    except Exception:
        grp = None

    return pwd, grp


def make_mode_string( statvals ):
    ""
    try:
        perm = stat.S_IMODE( statvals[ stat.ST_MODE ] )
        s = ''
        s += ( 'r' if perm & stat.S_IRUSR else '-' )
        s += ( 'w' if perm & stat.S_IWUSR else '-' )
        s += ( 'x' if perm & stat.S_IXUSR else '-' )
        s += ( 'r' if perm & stat.S_IRGRP else '-' )
        s += ( 'w' if perm & stat.S_IWGRP else '-' )
        s += ( 'x' if perm & stat.S_IXGRP else '-' )
        s += ( 'r' if perm & stat.S_IROTH else '-' )
        s += ( 'w' if perm & stat.S_IWOTH else '-' )
        s += ( 'x' if perm & stat.S_IXOTH else '-' )
        return s

    except Exception:
        return '?????????'


def get_stat_values( path ):
    ""
    try:
        if os.path.islink( path ):
            return 'l', os.lstat( path )
        else:
            statvals = os.stat( path )
            if os.path.isdir( path ):
                return 'd', statvals
            else:
                return '-', statvals
    except Exception:
        return '?', None


def get_path_owner( statvals, pwdmod ):
    ""
    uid = statvals[ stat.ST_UID ]
    try:
        return pwdmod.getpwuid( uid )[0]
    except Exception:
        return str( uid )


def get_path_group( statvals, grpmod ):
    ""
    gid = statvals[ stat.ST_GID ]
    try:
        return grpmod.getgrgid( gid )[0]
    except Exception:
        return str( gid )


def read_symlink( path ):
    ""
    try:
        if os.path.islink( path ):
            return os.readlink( path )
        return None
    except Exception:
        return ''
