#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
from os.path import join as pjoin
from os.path import normpath, abspath, basename, dirname
import shutil

from .errors import FatalError


SCRATCH_DIR_SEARCH_LIST = [ '/scratch',
                            '/var/scratch',
                            '/var/scratch1',
                            '/scratch1',
                            '/var/scratch2',
                            '/scratch2',
                            '/var/scrl1',
                            '/gpfs1' ]


def find_vvtest_test_root_file( start_directory,
                                stop_directory,
                                marker_filename ):
    """
    Starting at the 'start_directory', walks up parent directories looking
    for a 'marker_filename' file.  Stops looking when it reaches the
    'stop_directory' (excluding it) or "/".  Returns None if the marker
    filename is not found.  Returns the path to the marker file if found.
    """
    stopd = None
    if stop_directory:
        stopd = normpath( stop_directory )

    d = normpath( start_directory )

    while d and d != '/':

        mf = pjoin( d, marker_filename )

        if os.path.exists( mf ):
            return mf

        d = dirname( d )

        if stopd and d == stopd:
            break

    return None


def determine_configdir( opts_config, environ_config ):
    ""
    cfgL = []

    cfgspecs = []
    if opts_config:
        cfgspecs = opts_config
    elif environ_config and environ_config.strip():
        cfgspecs = [ environ_config.strip() ]

    for cfgdir in cfgspecs:
        if ':' in cfgdir:

            d1 = cfgdir
            while True:

                d1,d2 = split_by_largest_existing_path( d1 )

                if d1 == None:
                    d1,d2 = d2.split(':',1)

                if d1 != None:
                    cfgL.append( normpath( abspath(d1) ) )

                if d2 == None:
                    break
                elif ':' in d2:
                    d1 = d2
                else:
                    cfgL.append( normpath( abspath(d2) ) )
                    break

        else:
            cfgL.append( normpath( abspath( cfgdir ) ) )

    return cfgL


def split_by_largest_existing_path( path, rindex=0 ):
    ""
    if rindex == 0:
        d1 = path
        d2 = None
    else:
        pL = path.split(':')
        n = len(pL)

        if rindex >= n:
            d1 = None
            d2 = path
        else:
            d1 = ':'.join( pL[:n-rindex] )
            d2 = ':'.join( pL[n-rindex:] )

    if d1 == None or os.path.exists( d1 ):
        return d1,d2
    else:
        return split_by_largest_existing_path( path, rindex+1 )


def determine_test_directory( subdirname, test_cache_file, cwd ):
    ""
    if test_cache_file:
        assert os.path.isabs( test_cache_file )
        test_dir = normpath( dirname( test_cache_file ) )
    else:
        assert os.path.isabs( cwd )
        test_dir = normpath( pjoin( cwd, subdirname ) )

    return test_dir


def test_results_subdir_name( rundir, onopts, offopts, platform_name ):
    """
    Generates and returns the subdirectory name to hold test results, which is
    unique up to the platform and on/off options.
    """
    if rundir:
        testdirname = rundir

    else:
        testdirname = 'TestResults.' + platform_name
        if onopts and len(onopts) > 0:
          testdirname += '.ON=' + '_'.join( onopts )
        if offopts and len(offopts) > 0:
          testdirname += '.OFF=' + '_'.join( offopts )

    return testdirname


def create_test_directory( testdirname, Mval, curdir, perms ):
    """
    Create the given directory name.  If -M is given in the command line
    options, then a mirror directory is created and 'testdirname' will be
    created as a soft link pointing to the mirror directory.
    """
    assert os.path.isabs( testdirname )

    if Mval and make_mirror_directory( testdirname, Mval, curdir, perms ):
        pass

    else:
        if os.path.exists( testdirname ):
            if not os.path.isdir( testdirname ):
                # replace regular file with a directory
                os.remove( testdirname )
                os.mkdir( testdirname )
        else:
            if os.path.islink( testdirname ):
                os.remove( testdirname )  # remove broken softlink
            os.mkdir( testdirname )

        perms.set( testdirname )


def make_mirror_directory( testdirname, Mval, curdir, perms,
                           scratchdirs=SCRATCH_DIR_SEARCH_LIST ):
    """
    Create a directory in another location then soft link 'testdirname' to it.
    Returns False only if 'Mval' is the word "any" and a suitable scratch
    directory could not be found.
    """
    assert os.path.isabs( testdirname )

    if Mval == 'any':
        Mval = make_any_scratch_directory( scratchdirs, perms )
        if not Mval:
            return False

    elif not os.path.isabs( Mval ):
        Mval = pjoin( curdir, Mval )

    assert os.path.isabs( Mval )

    if not os.path.exists( Mval ) or not writable_directory( Mval ):
        raise FatalError( "invalid or non-existent mirror directory: "+Mval )

    if os.path.samefile( Mval, curdir ):
        raise FatalError( "mirror directory and current working directory " + \
                "cannot be the same: "+Mval+' == '+curdir )

    mirdir = pjoin( Mval, basename( testdirname ) )

    check_and_make_directory( mirdir )
    perms.set( mirdir )

    force_link_directory( testdirname, mirdir )

    return True


def force_link_directory( linkpath, targetpath ):
    ""
    if os.path.islink( linkpath ):
        path = os.readlink( linkpath )
        if path != targetpath:
            os.remove( linkpath )
            os.symlink( targetpath, linkpath )

    else:
        if os.path.exists( linkpath ):
            if os.path.isdir( linkpath ):
                shutil.rmtree( linkpath )
            else:
                os.remove( linkpath )
        os.symlink( targetpath, linkpath )


def check_and_make_directory( mirdir ):
    ""
    if os.path.exists( mirdir ):
        if not os.path.isdir( mirdir ):
            # replace regular file with a directory
            os.remove( mirdir )
            os.mkdir( mirdir )
    else:
        if os.path.islink( mirdir ):
            os.remove( mirdir )  # remove broken softlink
        os.mkdir( mirdir )


def make_any_scratch_directory( searchdirs, perms ):
    ""
    Mval = search_and_make_scratch_directory( searchdirs, perms )

    if not Mval:
        return None  # a scratch dir could not be found

    Mval = pjoin( Mval, 'vvtest_rundir' )

    if not os.path.exists( Mval ):
        os.mkdir( Mval )

    return Mval


def search_and_make_scratch_directory( searchdirs, perms ):
    ""
    for d in searchdirs:

        sdir = make_scratch_mirror( d, perms )
        if sdir:
            return sdir

    return None


def make_scratch_mirror( scratch, perms ):
    ""
    if os.path.exists( scratch ) and os.path.isdir( scratch ):

        usr = getUserName()
        ud = pjoin( scratch, usr )

        if os.path.exists(ud):
            if writable_directory(ud):
                return ud

        elif writable_directory( scratch ):
            try:
                os.mkdir(ud)
            except Exception:
                pass
            else:
                perms.set( ud )
                return ud

    return None


def writable_directory( path ):
    ""
    return os.path.isdir( path ) and \
           os.access( path, os.X_OK ) and \
           os.access( path, os.W_OK )


def getUserName():
    """
    Retrieves the user name associated with this process.
    """
    usr = None
    try:
        import getpass
        usr = getpass.getuser()
    except Exception:
        usr = None

    if usr == None:
        try:
            uid = os.getuid()
            import pwd
            usr = pwd.getpwuid( uid )[0]
        except Exception:
            usr = None

    if usr == None:
        try:
            p = os.path.expanduser( '~' )
            if p != '~':
                usr = basename( p )
        except Exception:
            usr = None

    if usr == None:
        # try manually checking the environment
        for n in ['USER', 'LOGNAME', 'LNAME', 'USERNAME']:
            if os.environ.get(n,'').strip():
                usr = os.environ[n]
                break

    if usr == None:
        raise Exception( "could not determine this process's user name" )

    return usr
