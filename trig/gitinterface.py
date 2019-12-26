#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import sys
sys.dont_write_bytecode = True
sys.excepthook = sys.__excepthook__
import os
from os.path import abspath, normpath, basename, dirname
from os.path import join as pjoin
import time
import pipes
import shutil
import tempfile
import subprocess
import re


class GitInterfaceError( Exception ):
    pass


class GitInterface:
    """
    Most functions take the optional 'verbose' keyword argument:

        0 : print nothing (this is the default)
        1 : print the git command
        2 : print the directory and git command, print output upon error
        3 : print the directory, the git command, and the output
    """

    def __init__(self, directory=None, **options):
        """
        If 'directory' is not None, then use it as the local repository.
        Otherwise assume current working directory.
        Options can be 'verbose', 'https_proxy', 'gitexe'.
        """
        verb = options.pop( 'verbose', 0 )

        self.grun = GitRunner( **options )

        self.top = get_repo_toplevel( self.grun, directory, verbose=verb )

    def get_toplevel(self, verbose=0):
        ""
        return self.top

    def add(self, *files, **kwargs):
        ""
        verbose = kwargs.pop( 'verbose', 0 )

        if len( files ) > 0:
            fL = [ pipes.quote(f) for f in files ]
            self.run( 'add', *fL, verbose=verbose )

    def commit(self, message, verbose=0):
        ""
        self.run( 'commit -m', pipes.quote(message), verbose=verbose )

    def push(self, all_branches=False, all_tags=False,
                   repository=None, verbose=0):
        """
        Pushes current branch by default.
            all_branches=True : push all branches
            all_tags=True : push all tags
            repository=URL : push to this repository (defaults to origin)
        """
        cmd = 'push'

        if all_branches or all_tags:
            if all_branches: cmd += ' --all'
            if all_tags:     cmd += ' --tags'

            if repository:
                cmd += ' '+repository

        else:
            br = self.get_branch()
            if not br:
                raise GitInterfaceError( 'you must be on a branch to push' )

            if repository:
                cmd += ' '+repository+' '+br
            else:
                cmd += ' origin '+br

        self.run( cmd, verbose=verbose )

    def pull(self, verbose=0):
        ""
        if self.is_bare():
            raise GitInterfaceError( 'cannot pull into a bare repository' )

        curbranch = self.get_branch()

        if curbranch == None:
            raise GitInterfaceError( 'cannot pull when HEAD is detached '
                    ' (which may be due to a previous merge conflict' )

        self.run( 'tag GITINTERFACE_PULL_BACKUP', verbose=verbose )

        try:
            self.run( 'pull', verbose=verbose )

        except Exception:
            self.run( 'reset --hard GITINTERFACE_PULL_BACKUP', verbose=verbose )
            self.run( 'checkout '+curbranch, verbose=verbose )
            self.run( 'tag -d GITINTERFACE_PULL_BACKUP', verbose=verbose )
            raise GitInterfaceError( 'pull failed (probably merge conflict)' )

        self.run( 'tag -d GITINTERFACE_PULL_BACKUP' )

    def get_branch(self, verbose=0):
        """
        The current branch name, or None if in a detached HEAD state.
        """
        x,out = self.run( 'branch', capture=True, verbose=verbose )

        for line in out.splitlines():
            if line.startswith( '* (' ):
                return None  # detatched
            elif line.startswith( '* ' ):
                return line[2:].strip()

        raise GitInterfaceError( 'no branches found, DIR='+str(self.top) )

    def get_branches(self, remotes=False, verbose=0):
        ""
        bL = []

        cmd = 'branch'
        if remotes:
            cmd += ' -r'

        x,out = self.run( cmd, capture=True, verbose=verbose )

        for line in out.splitlines():
            if line.startswith( '* (' ):
                pass
            elif line.startswith( '* ' ) or line.startswith( '  ' ):
                if ' -> ' not in line:
                    line = line[2:]
                    if line.startswith( 'origin/' ):
                        line = line[7:]
                    bL.append( line )

        bL.sort()
        return bL

    def checkout_branch(self, branchname, verbose=0):
        ""
        if branchname != self.get_branch():
            if branchname in self.get_branches():
                self.run( 'checkout', branchname, verbose=verbose )
            elif branchname in self.get_branches( remotes=True ):
                self.run( 'checkout --track origin/'+branchname, verbose=verbose )
            else:
                url = self.get_remote_URL()
                if url and branchname in get_remote_branches( url, verbose=verbose):
                    self._fetch_then_checkout_branch( branchname, verbose=verbose )
                else:
                    raise GitInterfaceError( 'branch does not exist: '+branchname )

    def create_branch(self, branchname, verbose=0):
        ""
        if branchname in self.get_branches():
            raise GitInterfaceError( 'branch already exists: '+branchname )

        self.run( 'checkout -b '+branchname, verbose=verbose )

    def get_remote_URL(self, verbose=0):
        ""
        x,out = self.run( 'config --get remote.origin.url',
                          raise_on_error=False, capture=True,
                          verbose=verbose )
        if x != 0:
            return None
        return out.strip()

    def createRemoteBranch(self, branchname, verbose=0):
        """
        Create a branch on the remote, checkout, and track it locally.
        Any local changes are not pushed, but are merged onto the new branch.
        """
        curbranch = self.get_branch()

        url = self.get_remote_URL()
        if not url:
            raise GitInterfaceError( 'no remote URL for origin in config file' )

        if branchname in get_remote_branches( url, verbose=verbose ):
            raise GitInterfaceError(
                    'branch name already exists on remote: '+branchname )

        if curbranch not in self.get_branches( remotes=True ):
            raise GitInterfaceError(
                    'current branch must be tracking a remote: '+curbranch )

        self.run( 'branch', branchname, 'origin/'+curbranch, verbose=verbose )
        self.run( 'checkout', branchname, verbose=verbose )
        self.run( 'push -u origin', branchname, verbose=verbose )
        self.run( 'merge', curbranch, verbose=verbose )

    def createRemoteOrphanBranch(self, branchname, message, path0, *paths,
                                       **kwargs):
        """
        Create and push a branch containing a copy of the given paths
        (files and/or directories), with the given intial commit message.
        It will share no history with any other branch.
        """
        verbose = kwargs.get( 'verbose', 0 )

        if not self.get_branch():
            raise GitInterfaceError( 'must currently be on a branch' )

        url = self.get_remote_URL()
        if not url:
            raise GitInterfaceError( 'no remote URL for origin in config file' )

        if branchname in get_remote_branches( url, verbose=verbose ):
            raise GitInterfaceError(
                    'branch name already exists on remote: '+branchname )

        # newer versions of git have a git checkout --orphan option; the
        # implementation here creates a temporary repo with an initial
        # commit then fetches that into the current repository

        pathL = [ abspath(p) for p in (path0,)+paths ]

        tmpdir = tempfile.mkdtemp( '.gitinterface' )
        try:
            with change_directory( tmpdir ):
                _create_repo_with_files( self.grun, message, pathL,
                                         verbose=verbose )

            with change_directory( self.get_toplevel() ):
                self.run( 'fetch', tmpdir, 'master:'+branchname, verbose=verbose )
                self.run( 'checkout', branchname, verbose=verbose )
                self.run( 'push -u origin', branchname, verbose=verbose )

        finally:
            shutil.rmtree( tmpdir )

    def deleteRemoteBranch(self, branchname, verbose=0):
        ""
        curbranch = self.get_branch()
        if branchname == curbranch:
            raise GitInterfaceError(
                    'cannot delete current branch: '+branchname )

        url = self.get_remote_URL()
        if not url:
            raise GitInterfaceError( 'no remote URL for origin in config file' )

        if branchname not in get_remote_branches( url, verbose=verbose ):
            raise GitInterfaceError(
                    'branch name does not exist on remote: '+branchname )

        if branchname in self.get_branches():
            self.run( 'branch -d', branchname )

        self.run( 'push --delete origin', branchname, verbose=verbose )

    def get_tags(self, verbose=0):
        ""
        x,out = self.run( 'tag --list --no-column',
                          capture=True, verbose=verbose )

        tagL = []

        for line in out.strip().splitlines():
            tag = line.strip()
            if tag:
                tagL.append( tag )

        tagL.sort()

        return tagL

    def is_bare(self, verbose=0):
        ""
        x,out = self.run( 'rev-parse --is-bare-repository',
                          capture=True, verbose=verbose )

        val = out.strip().lower()
        if val == 'true':
            return True
        elif val == 'false':
            return False
        else:
            raise GitInterfaceError(
                        'unexpected response from rev-parse: '+str(out) )

    def _fetch_then_checkout_branch(self, branchname, verbose=0):
        ""
        self.run( 'fetch origin' )

        x,out = self.run( 'checkout --track origin/'+branchname,
                          raise_on_error=False, capture=True,
                          verbose=verbose )
        if x != 0:
            # try adding the branch in the fetch list
            x,out2 = self.run( 'config --add remote.origin.fetch ' + \
                               '+refs/heads/'+branchname + \
                               ':refs/remotes/origin/'+branchname,
                               raise_on_error=False, capture=True,
                               verbose=verbose )
            out += out2

            if x == 0:
                x,out3 = self.run( 'fetch origin',
                                   raise_on_error=False, capture=True,
                                   verbose=verbose )
                out += out3

                if x == 0:
                    x,out4 = self.run( 'checkout --track origin/'+branchname,
                                       raise_on_error=False, capture=True,
                                       verbose=verbose )
                    out += out4

            if x != 0:
                if verbose >= 2:
                    print3( out )
                raise GitInterfaceError( 'branch appears on remote but ' + \
                                'fetch plus checkout failed: '+branchname )

    def run(self, arg0, *args, **kwargs):
        ""
        kwargs['chdir'] = self.top
        return self.grun.run( arg0, *args, **kwargs )


def create_repo( directory=None, bare=False, **options):
    """
    If 'directory' is not None, it is created and will contain the new repo.
    Otherwise the current directory is used.

    Options can be 'https_proxy', 'gitexe', and 'verbose'.

    Returns a GitInterface object set to the new repo.
    """
    verb = options.pop( 'verbose', 0 )

    grun = GitRunner( **options )

    cmd = 'init'
    if bare:
        cmd += ' --bare'

    if directory:
        cd, name = _split_and_create_directory( directory )
        cmd += ' '+name
        top = normpath( abspath( directory ) )
    else:
        cd = None
        top = os.getcwd()

    grun.run( cmd, chdir=cd, verbose=verb )

    return GitInterface( directory=top, **options )


def clone_repo( url, directory=None, branch=None, bare=False, **options ):
    """
    If 'branch' is None, all branches are fetched.  If a branch name (such
    as "master") then only that branch is fetched.  If 'directory' is not
    None, it will contain the repository.

    Options can be 'verbose', 'https_proxy', 'gitexe'.

    Returns a GitInterface object set to the cloned repository.
    """
    verb = options.pop( 'verbose', 0 )

    grun = GitRunner( **options )

    if branch and bare:
        raise GitInterfaceError( 'cannot bare clone a single branch' )

    if branch:
        top = _branch_clone( grun, url, directory, branch, verb )
    else:
        top = _full_clone( grun, url, directory, bare, verb )

    options['verbose'] = verb
    return GitInterface( top, **options )


def get_remote_branches( url, verbose=0 ):
    """
    Get the list of branches on the remote repository 'url' (which can be
    a directory).
    """
    bL = []

    grun = GitRunner()
    x,out = grun.run( 'ls-remote --heads', url, capture=True, verbose=verbose )

    for line in out.strip().splitlines():
        lineL = line.strip().split( None, 1 )
        if len( lineL ) == 2:
            if lineL[1].startswith( 'refs/heads/' ):
                bL.append( lineL[1][11:] )

    bL.sort()

    return bL


def safe_repository_mirror( from_url, to_url, work_clone=None, verbose=0 ):
    ""
    if work_clone:

        if os.path.isdir( work_clone ):
            with change_directory( work_clone ):
                work_git = GitInterface()
                mirror_remote_repo_into_pwd( from_url, verbose=verbose )
                push_branches_and_tags( work_git, to_url, verbose=verbose )

        else:
            work_git = clone_repo( from_url, directory=work_clone,
                                   bare=True, verbose=verbose )
            push_branches_and_tags( work_git, to_url, verbose=verbose )

    else:
        tdir = tempfile.mkdtemp( dir=os.getcwd() )

        try:
            work_git = clone_repo( from_url, directory=tdir, bare=True, verbose=verbose )
            push_branches_and_tags( work_git, to_url, verbose=verbose )

        finally:
            shutil.rmtree( tdir )


def mirror_remote_repo_into_pwd( remote_url, verbose=0 ):
    ""
    git = GitInterface()

    if not git.is_bare():
        raise GitInterfaceError( 'work_clone must be a bare repository' )

    git.run( 'fetch', remote_url,
             '"refs/heads/*:refs/heads/*"',
             '"refs/tags/*:refs/tags/*"',
             verbose=verbose )


def push_branches_and_tags( work_git, to_url, verbose=0 ):
    ""
    work_git.push( all_branches=True, repository=to_url, verbose=verbose )
    work_git.push( all_tags=True, repository=to_url, verbose=verbose )


# match the form [user@]host.xz:path/to/repo.git/
scp_like_url = re.compile( r'([a-zA-Z0-9_]+@)?[a-zA-Z0-9_]+([.][a-zA-Z0-9_]*)*:' )

def repository_url_match( url ):
    ""
    if url.startswith( 'http://' ) or url.startswith( 'https://' ) or \
       url.startswith( 'ftp://' ) or url.startswith( 'ftps://' ) or \
       url.startswith( 'ssh://' ) or \
       url.startswith( 'git://' ) or \
       url.startswith( 'file://' ):
        return True

    elif scp_like_url.match( url ):
        return True

    return False


def is_a_local_repository( directory ):
    ""
    if not os.path.isdir( directory ) and os.path.isdir( directory+'.git' ):
        directory += '.git'

    try:
        git = GitInterface( directory )
        x,out = git.run( 'rev-parse --is-bare-repository',
                         raise_on_error=False, capture=True )
    except Exception:
        return False

    if x == 0 and out.strip().lower() in ['true','false']:
        return True

    return False


def verify_repository_url( url ):
    ""
    if is_a_local_repository( url ):
        return True

    else:
        grun = GitRunner()
        x,out = grun.run( 'ls-remote', url,
                          raise_on_error=False, capture=True )
        if x == 0:
            return True

    return False


########################################################################

class GitRunner:

    def __init__(self, **options):
        ""
        self.envars = {}

        self.gitexe = options.pop( 'gitexe', 'git' )

        prox = options.pop( 'https_proxy', None )
        if prox:
            self.envars['https_proxy'] = prox
            self.envars['HTTPS_PROXY'] = prox

        if len( options ) > 0:
            raise GitInterfaceError( "unknown options: "+str(options) )

    def run(self, arg0, *args, **kwargs):
        ""
        roe = kwargs.pop( 'raise_on_error', True )
        cap = kwargs.pop( 'capture', False )
        cd = kwargs.pop( 'chdir', None )
        verbose = kwargs.pop( 'verbose', 0 )

        assert len(kwargs) == 0

        cmd = self.gitexe + ' ' + ' '.join( (arg0,)+args )

        with set_environ( **self.envars ):
            x,out = runcmd( cmd,
                            chdir=cd,
                            raise_on_error=roe,
                            capture=cap,
                            verbose=verbose )

        return x, out


def get_repo_toplevel( gitrun, directory=None, verbose=0 ):
    ""
    if not directory:
        directory = os.getcwd()

    with change_directory( directory ):
        x,top = gitrun.run( 'rev-parse --show-toplevel',
                            raise_on_error=False, capture=True,
                            verbose=verbose )
        top = top.strip()

    if x == 0 and not top:
        top = _find_toplevel_bare_git_repo( directory )
        if basename( top ) == '.git':
            # must be in the .git subdirectory of a clone
            top = dirname( top )

    if x != 0 or not top:
        raise GitInterfaceError( 'could not determine top level '
                                 '(are you in a Git repo?) '+str(directory) )

    return top


def _find_toplevel_bare_git_repo( directory ):
    ""
    top = ''

    d0 = directory
    while True:
        d1 = dirname( d0 )
        if _is_toplevel_bare_git_repo(d0):
            top = d0
            break
        elif d0 == d1:
            break
        d0 = d1

    return top


def _is_toplevel_bare_git_repo( directory ):
    ""
    br  = pjoin( directory, 'branches' )
    cfg = pjoin( directory, 'config' )
    if os.path.isdir(br) and os.path.isfile(cfg):
        return True
    return False


def repo_name_from_url( url ):
    ""
    name = basename( normpath(url) )
    if name.endswith( '.git' ):
        name = name[:-4]
    return name


def _branch_clone( grun, url, directory, branch, verbose ):
    ""
    if not directory:
        directory = repo_name_from_url( url )

    with make_and_change_directory( directory ):
        grun.run( 'init', verbose=verbose )
        grun.run( 'remote add -f -t', branch, '-m', branch, 'origin', url,
                  verbose=verbose )
        grun.run( 'checkout', branch, verbose=verbose )
        top = os.getcwd()

    return top


def _full_clone( grun, url, directory, bare, verbose ):
    ""
    cmd = 'clone'
    if bare:
        cmd += ' --bare'

    if directory:
        if not repository_url_match( url ) and is_a_local_repository( url ):
            url = abspath( url )

        with make_and_change_directory( directory ):
            grun.run( cmd, url, '.', verbose=verbose )
            top = os.getcwd()

    else:
        grun.run( cmd, url, verbose=verbose )

        dname = _repo_directory_from_url( url, bare )

        assert os.path.isdir( dname )
        top = abspath( dname )

    return top


def _repo_directory_from_url( url, bare=False ):
    ""
    name = repo_name_from_url( url )
    if bare:
        return name+'.git'
    else:
        return name


class change_directory:

    def __init__(self, directory):
        ""
        self.cwd = os.getcwd()
        self.directory = directory

    def __enter__(self):
        ""
        if self.directory:
            assert os.path.isdir( self.directory )
            os.chdir( self.directory )

    def __exit__(self, type, value, traceback):
        ""
        os.chdir( self.cwd )


class make_and_change_directory( change_directory ):

    def __enter__(self):
        ""
        if not os.path.exists( self.directory ):
            os.makedirs( self.directory )

        change_directory.__enter__( self )


class set_environ:

    def __init__(self, **name_value_pairs):
        """
        If the value is None, the name is removed from os.environ.
        """
        self.pairs = name_value_pairs

    def __enter__(self):
        ""
        self.save_environ = dict( os.environ )

        for n,v in self.pairs.items():
            if v == None:
                if n in os.environ:
                    del os.environ[n]
            else:
                os.environ[n] = v

    def __exit__(self, type, value, traceback):
        ""
        for n,v in self.pairs.items():
            if n in self.save_environ:
                os.environ[n] = self.save_environ[n]
            elif v != None:
                del os.environ[n]


def _split_and_create_directory( repo_path ):
    ""
    path,name = os.path.split( normpath( repo_path ) )

    if path == '.':
        path = ''

    if path and not os.path.exists( path ):
        os.makedirs( path )

    return path, name


def copy_path_to_current_directory( filepath ):
    ""
    bn = basename( filepath )

    if os.path.islink( filepath ):
        os.symlink( os.readlink( filepath ), bn )
    elif os.path.isdir( filepath ):
        shutil.copytree( filepath, bn, symlinks=True )
    else:
        shutil.copyfile( filepath, bn )

    return bn


def _create_repo_with_files( gitrun, message, pathL, verbose=0 ):
    ""
    gitrun.run( 'init', verbose=verbose )

    fL = []
    for pn in pathL:
        fn = copy_path_to_current_directory( pn )
        fL.append( pipes.quote(fn) )

    gitrun.run( 'add', *fL, verbose=verbose )
    gitrun.run( 'commit -m', pipes.quote( message ), verbose=verbose )


def runcmd( cmd, chdir=None,
                 raise_on_error=True,
                 capture=False,
                 verbose=0 ):
    ""
    out = ''
    err = ''
    x = 1

    if verbose >= 2:
        if chdir:
            print3( 'cd', chdir, '\n'+cmd )
        else:
            print3( 'PWD='+os.getcwd(), '\n'+cmd )
    elif verbose == 1:
        print3( cmd )

    collect = ( capture or verbose < 3 )

    with change_directory( chdir ):

        if collect:
            po = subprocess.Popen( cmd, shell=True, stdout=subprocess.PIPE,
                                                    stderr=subprocess.PIPE )
        else:
            po = subprocess.Popen( cmd, shell=True )

        sout,serr = po.communicate()
        x = po.returncode

        if sout != None:
            out = _STRING_(sout)

        if serr != None:
            err = _STRING_(serr)

    if x != 0:
        if collect and verbose >= 2:
            flush_stdout_err( out, err )
        if raise_on_error:
            raise GitInterfaceError( 'Command failed: '+cmd )

    elif collect and verbose >= 3:
        flush_stdout_err( out, err )

    return x,out


def flush_stdout_err( out, err ):
    ""
    if out:
        sys.stdout.write( '\n'+out )
        sys.stdout.flush()
    if err:
        sys.stderr.write( '\n'+err )
        sys.stderr.flush()


if sys.version_info[0] < 3:
    def _STRING_(b): return b

else:
    bytes_type = type( ''.encode() )

    def _STRING_(b):
        if type(b) == bytes_type:
            return b.decode()
        return b


def print3( *args ):
    sys.stdout.write( ' '.join( [ str(x) for x in args ] ) + '\n' )
    sys.stdout.flush()
