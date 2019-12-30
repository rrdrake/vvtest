#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import getopt
import re
import tempfile
import shutil
import filecmp
import glob
import pipes
from os.path import join as pjoin
from os.path import abspath, normpath, basename, dirname

import gitinterface as gititf
from gitinterface import change_directory


MANIFESTS_FILENAME = 'manifests.mrgit'
GENESIS_FILENAME = 'genesis.map'
REPOMAP_BRANCH = 'mrgit_repo_map'
REPOMAP_FILENAME = 'repomap'
REPOMAP_TEMPFILE = 'repomap.tmp'


class MRGitExitError( Exception ):
    pass


def errorexit( *args ):
    ""
    err = ' '.join( [ str(arg) for arg in args ] )
    raise MRGitExitError( err )


def clone( argv ):
    ""
    optL,argL = getopt.getopt( argv, 'G', [] )

    optD = {}
    for n,v in optL:
        optD[n] = v

    if len( argL ) > 0:

        urls, directory = parse_url_list( argL )
        assert len( urls ) > 0

        cfg = Configuration()

        if '-G' in optD:
            if len(urls) != 1:
                errorexit( 'must specify exactly one URL with the -G option' )
            clone_from_google_repo_manifests( cfg, urls[0], directory )

        elif len( urls ) == 1:
            clone_from_single_url( cfg, urls[0], directory )

        else:
            clone_from_multiple_urls( cfg, urls, directory )

        cfg.commitLocalRepoMap()


def init( argv ):
    ""
    cfg = Configuration()
    cfg.setTopLevel( os.getcwd() )
    cfg.createMRGitRepo()


def fetch( argv ):
    ""
    cfg = load_configuration()

    top = cfg.getTopLevel()
    for path in cfg.getLocalRepoPaths():
        git = gititf.GitRepo( pjoin( top, path ) )
        git.run( 'fetch', verbose=3 )


def pull( argv ):
    ""
    cfg = load_configuration()

    top = cfg.getTopLevel()
    for path in cfg.getLocalRepoPaths():
        git = gititf.GitRepo( pjoin( top, path ) )
        git.run( 'pull', verbose=3 )


def add( argv ):
    ""
    cfg = load_configuration()

    top = cfg.getTopLevel()
    for path in cfg.getLocalRepoPaths():
        git = gititf.GitRepo( pjoin( top, path ) )
        args = [ pipes.quote(arg) for arg in argv ]
        git.run( 'add', *args, verbose=3 )


def commit( argv ):
    ""
    cfg = load_configuration()

    top = cfg.getTopLevel()
    for path in cfg.getLocalRepoPaths():
        git = gititf.GitRepo( pjoin( top, path ) )
        args = [ pipes.quote(arg) for arg in argv ]
        git.run( 'commit', *args, verbose=3 )


def push( argv ):
    ""
    cfg = load_configuration()

    top = cfg.getTopLevel()
    for path in cfg.getLocalRepoPaths():
        git = gititf.GitRepo( pjoin( top, path ) )
        git.run( 'push', verbose=3 )


def load_configuration():
    ""
    cfg = Configuration()

    top = find_mrgit_top_level()
    cfg.setTopLevel( top )
    git = gititf.GitRepo( top+'/.mrgit' )
    read_mrgit_manifests_file( cfg.getManifests(), top )
    cfg.computeLocalRepoMap()

    return cfg


def find_mrgit_top_level():
    ""
    top = None

    d1 = os.getcwd()
    while True:
        if os.path.isdir( pjoin( d1, '.mrgit' ) ):
            top = d1
            break
        d2 = dirname( d1 )
        if not d2 or d1 == d2:
            break
        d1 = d2

    return top


def parse_url_list( args ):
    ""
    directory = None
    urls = []

    if len( args ) < 1:
        pass

    elif len( args ) == 1:
        urls = [ make_absolute_url_path( args[0] ) ]

    elif specifies_a_repository( args[-1] ):
        urls = [ make_absolute_url_path(url) for url in args ]

    else:
        directory = args[-1]
        urls = [ make_absolute_url_path(url) for url in args[:-1] ]

    return urls, directory


def specifies_a_repository( url ):
    ""
    return gititf.repository_url_match( url ) or \
           gititf.is_a_local_repository( url ) or \
           gititf.is_a_local_repository( url+'/.mrgit' )


def make_absolute_url_path( url ):
    ""
    if gititf.repository_url_match( url ):
        if url == 'file://':
            raise MRGitExitError( 'invalid URL: '+repr(url) )
        elif url.startswith( 'file://' ):
            tail = url[7:]
            absurl = 'file://'+abspath( tail )
        else:
            absurl = url
    else:
        absurl = abspath( url )

    return absurl


def clone_from_single_url( cfg, url, directory ):
    ""
    tmptop = TempDirectory( directory )
    cfg.setTopLevel( tmptop.path() )

    try:
        # prefer a .mrgit repo under the given url
        git = temp_clone( url+'/.mrgit', tmptop.path() )

    except gititf.GitInterfaceError:
        # that failed, so just clone the given url
        git = temp_clone( url, tmptop.path() )

    upstream = check_for_mrgit_repo( git )

    if upstream:

        # we just cloned an mrgit or genesis repo

        # make new clone the .mrgit directory
        mrgit = tmptop.path()+'/.mrgit'
        assert not os.path.islink( mrgit ) and not os.path.exists( mrgit )
        os.rename( git.get_toplevel(), mrgit )

        # magic: can the repo be moved/renamed to .mrgit right here??
        #   - then the manifest can be loaded by the upstream
        #   - goal is move cfg construction into the upstreams, which can
        #     be reused for cfg construction of local mrgit case (as well as
        #     reducing the code in this bootstrapping region)

        upstream.fillManifests( cfg.getManifests(), tmptop.path() )
        upstream.fillRepoMap( cfg.getRemoteMap(), tmptop.path() )
        cfg.computeLocalRepoMap()

        clone_repositories_from_config( cfg )

        topdir = upstream.computeTopLevel( cfg, directory )
        tmptop.rename( topdir )

    else:
        # repo is not an mrgit or genesis repo
        upstream = UpstreamURLs( [ url ] )
        upstream.fillManifests( cfg.getManifests() )
        upstream.fillRepoMap( cfg.getRemoteMap(), None )
        cfg.computeLocalRepoMap()
        cfg.createMRGitRepo()

        url,loc = cfg.getRemoteRepoList()[0]
        os.rename( git.get_toplevel(), pjoin( tmptop.path(), loc ) )

        topdir = upstream.computeTopLevel( cfg, directory )
        tmptop.rename( topdir )


def clone_from_multiple_urls( cfg, urls, directory ):
    ""
    upstream = UpstreamURLs( urls )
    upstream.fillManifests( cfg.getManifests() )
    upstream.fillRepoMap( cfg.getRemoteMap(), None )
    cfg.computeLocalRepoMap()
    upstream.computeTopLevel( cfg, directory )
    clone_repositories_from_config( cfg )
    cfg.createMRGitRepo()



def clone_from_google_repo_manifests( cfg, url, directory ):
    ""
    tmptop = TempDirectory( directory )

    git = temp_clone( url, tmptop.path() )
    tmpbname = basename( git.get_toplevel() )

    gconv = GoogleConverter( git.get_toplevel() )
    gconv.readManifestFiles()
    gconv.fillManifests( cfg.getManifests() )

    top = gconv.computeTopLevel( cfg, directory )
    tmptop.rename( top )

    cfg.computeLocalRepoMap()
    gconv.fillRepoMap( cfg.getRemoteMap(), None )
    cfg.createMRGitRepo()

    src = pjoin( top, tmpbname )
    dst = pjoin( top, '.mrgit', 'google_manifests' )
    move_directory_contents( src, dst )

    clone_repositories_from_config( cfg )


class MRGitUpstream:

    def __init__(self, url):
        ""
        # should always end in "/.mrgit", such as file:///some/path/.mrgit
        self.url = url

    def remoteName(self):
        ""
        return gititf.repo_name_from_url( dirname( self.url ) )

    def fillManifests(self, mfest, toplevel):
        ""
        read_mrgit_manifests_file( mfest, toplevel )

    def computeTopLevel(self, cfg, directory):
        ""
        top = compute_path_for_toplevel( directory,
                                         cfg.getManifests(),
                                         self.remoteName() )
        cfg.setTopLevel( top )

        return top

    def fillRepoMap(self, rmap, toplevel):
        ""
        git = gititf.GitRepo( toplevel+'/.mrgit' )
        read_mrgit_repo_map_file( rmap, dirname( self.url ), git )


class GenesisUpstream:

    def __init__(self, url):
        ""
        self.url = url

    def remoteName(self):
        ""
        return gititf.repo_name_from_url( self.url )

    def fillManifests(self, mfest, toplevel):
        ""
        read_mrgit_manifests_file( mfest, toplevel )

    def computeTopLevel(self, cfg, directory):
        ""
        top = compute_path_for_toplevel( directory,
                                         cfg.getManifests(),
                                         self.remoteName() )
        cfg.setTopLevel( top )

        return top

    def fillRepoMap(self, rmap, toplevel):
        ""
        git = gititf.GitRepo( toplevel+'/.mrgit' )
        read_genesis_map_file( rmap, git )


def compute_path_for_toplevel( directory, mfest, remotename ):
    ""
    if directory:
        top = normpath( abspath( directory ) )
    else:
        top = path_for_toplevel( mfest, remotename )

    return top


def path_for_toplevel( mfest, remotename ):
    ""
    grp = mfest.getDefaultGroup()
    if grp == None:
        # only from an empty mrgit init, or a clone of one
        top = abspath( remotename )

    elif grp.getName():
        top = abspath( grp.getName() )

    else:
        # when cloning a repo which is a clone of a list of URLs
        top = abspath( '.' )

    return top


class UpstreamURLs:

    def __init__(self, url_list):
        ""
        self.urls = url_list

    def computeTopLevel(self, cfg, directory):
        ""
        if directory:
            top = directory
        else:
            top = '.'

        cfg.setTopLevel( normpath( abspath( top ) ) )

        return top

    def fillManifests(self, mfest):
        ""
        groupname = ''
        for url in self.urls:
            name = gititf.repo_name_from_url( url )
            mfest.addRepo( groupname, name, name )

    def fillRepoMap(self, rmap, toplevel):  # toplevel not needed here
        ""
        for url in self.urls:
            name = gititf.repo_name_from_url( url )
            rmap.setRepoLocation( name, url=url )


class GoogleConverter:

    def __init__(self, manifests_directory):
        ""
        self.srcdir = manifests_directory

    def readManifestFiles(self):
        ""
        fn = pjoin( self.srcdir, 'default.xml' )
        self.default = GoogleManifestReader( fn )
        self.default.createRepoNameToURLMap()

        self.manifests = []
        for fn in glob.glob( pjoin( self.srcdir, '*.xml' ) ):
            gmr = GoogleManifestReader( fn )
            gmr.createRepoNameToURLMap()
            self.manifests.append( gmr )

    def getPrimaryURL(self, repo_name):
        """
        The repo XML syntax allows for different Git remote URLs for the
        same repository name.  The "primary" URL for a repository name is
        the one specified in the defaults.xml, or if not there then it is
        the most common one in all of the manifest XML files.
        """
        url = self.default.getRepoURL( repo_name, None )

        if not url:
            url2cnt = self._count_urls( repo_name )
            sortL = [ (T[1],T[0]) for T in url2cnt.items() ]
            sortL.sort()
            url = sortL[-1][1]

        return url

    def fillRepoMap(self, rmap, toplevel):
        ""
        for gmr in [ self.default ] + self.manifests:
            for reponame in gmr.getRepoNames():
                url = self.getPrimaryURL( reponame )
                rmap.setRepoLocation( reponame, url )

    def fillManifests(self, mfest):
        ""
        for gmr in [ self.default ] + self.manifests:
            self._create_group_from_manifest( gmr, mfest )

    def computeTopLevel(self, cfg, directory):
        ""
        if directory:
            top = normpath( abspath( directory ) )
        else:
            gname = self.default.getGroupName()
            assert gname, 'default google manifest group name cannot be empty'
            top = normpath( abspath( gname ) )

        cfg.setTopLevel( top )

        return top

    def _create_group_from_manifest(self, gmr, mfest):
        ""
        if self._all_urls_are_primary( gmr ):
            for name,url,path in gmr.getProjectList():
                groupname = gmr.getGroupName()
                mfest.addRepo( groupname, name, path )

    def _all_urls_are_primary(self, gmr):
        ""
        for name,url,path in gmr.getProjectList():
            primary = self.getPrimaryURL( name )
            if url != primary:
                return False

        return True

    def _count_urls(self, repo_name):
        ""
        url2cnt = {}

        for mfest in self.manifests:
            url = mfest.getRepoURL( repo_name, None )
            if url:
                url2cnt[ url ] = url2cnt.get( url, 0 ) + 1

        return url2cnt


class GoogleManifestReader:

    def __init__(self, filename):
        ""
        # put this here instead of the top of this file because reading Google
        # manifests is not core to mrgit, but if it was at the top and the
        # import failed, then the application would crash
        import xml.etree.ElementTree as ET

        self.name = os.path.splitext( basename( filename ) )[0]
        self.urlmap = {}

        self.xmlroot = ET.parse( filename ).getroot()

    def createRepoNameToURLMap(self):
        ""
        self.urlmap = {}

        self.default_remote = self._get_default_remote_name()
        self.remotes = self._collect_remote_prefix_urls()

        for nd in self.xmlroot:
            if nd.tag == 'project':
                url = self._get_project_url( nd )
                name = self._get_project_name( nd )

                assert name not in self.urlmap
                self.urlmap[name] = url

        return self.urlmap

    def getGroupName(self):
        ""
        return self.name

    def getRepoNames(self):
        ""
        return self.urlmap.keys()

    def getRepoURL(self, repo_name, *default):
        ""
        if len(default) > 0:
            return self.urlmap.get( repo_name, default[0] )
        return self.urlmap[repo_name]

    def getProjectList(self):
        ""
        projects = []

        for nd in self.xmlroot:
            if nd.tag == 'project':
                name = self._get_project_name( nd )
                url = self.urlmap[ name ]
                path = self._get_project_path( nd )

                projects.append( ( name, url, path ) )

        return projects

    def _collect_remote_prefix_urls(self):
        ""
        remotes = {}

        for nd in self.xmlroot:
            if nd.tag == 'remote':
                name = nd.attrib['name'].strip()
                prefix = nd.attrib['fetch'].strip()
                remotes[name] = prefix

        return remotes

    def _get_project_name(self, xmlnd):
        ""
        return xmlnd.attrib['name'].strip()

    def _get_project_url(self, xmlnd):
        ""
        name = self._get_project_name( xmlnd )
        remote = xmlnd.attrib.get( 'remote', self.default_remote ).strip()
        prefix = self.remotes[remote]
        url = append_path_to_url( prefix, name )

        return url

    def _get_project_path(self, xmlnd):
        ""
        path = xmlnd.attrib.get( 'path', '.' )
        if not path: path = '.'
        path = normpath( path )

        return path

    def _get_default_remote_name(self):
        ""
        for nd in self.xmlroot:
            if nd.tag == 'default':
                return nd.attrib['remote'].strip()


def clone_repositories_from_config( cfg ):
    ""
    topdir = cfg.getTopLevel()

    check_make_directory( topdir )

    with change_directory( topdir ):
        for url,loc in cfg.getRemoteRepoList():
            robust_clone( url, loc )


def robust_clone( url, into_dir, verbose=2 ):
    ""
    if os.path.exists( into_dir ):

        assert '.git' not in os.listdir( into_dir )

        tmp = tempfile.mkdtemp( '', 'mrgit_tempclone_', abspath( into_dir ) )
        gititf.clone_repo( url, tmp, verbose=verbose )
        move_directory_contents( tmp, into_dir )

        git = gititf.GitRepo( into_dir )

    else:
        git = gititf.clone_repo( url, into_dir, verbose=verbose )

    return git


def temp_clone( url, chdir, verbose=1 ):
    ""
    subd = tempfile.mkdtemp( '', 'mrgit_tempclone_', abspath( chdir ) )
    try:
        git = gititf.clone_repo( url, subd, verbose=verbose )
    except Exception:
        shutil.rmtree( subd )
        raise

    return git


class TempDirectory:

    def __init__(self, directory):
        ""
        if directory and os.path.isdir( directory ):
            self.isnew = False
            self.tmpd = abspath( directory )
        else:
            self.isnew = True
            self.tmpd = tempfile.mkdtemp( '', 'mrgit_tmpdir_', os.getcwd() )

    def path(self):
        ""
        return self.tmpd

    def rename(self, todir):
        ""
        if self.isnew:
            move_directory_contents( self.tmpd, todir )


def check_for_mrgit_repo( git ):
    ""
    mfestfn = pjoin( git.get_toplevel(), MANIFESTS_FILENAME )
    genfn = pjoin( git.get_toplevel(), GENESIS_FILENAME )

    if os.path.isfile( mfestfn ):
        if REPOMAP_BRANCH in git.get_branches() or \
           REPOMAP_BRANCH in git.get_branches( remotes=True ):

            return MRGitUpstream( git.get_remote_URL() )

        elif os.path.isfile( genfn ):
            return GenesisUpstream( git.get_remote_URL() )

    return None


def remove_all_files_in_directory( path ):
    ""
    for fn in os.listdir( path ):
        dfn = pjoin( path, fn )
        if os.path.isdir( dfn ):
            shutil.rmtree( dfn )
        else:
            os.remove( dfn )


def move_directory_contents( fromdir, todir ):
    ""
    if os.path.exists( todir ):
        for fn in os.listdir( fromdir ):
            frompath = pjoin( fromdir, fn )
            shutil.move( frompath, todir )
        shutil.rmtree( fromdir )

    else:
        os.rename( fromdir, todir )


def check_make_directory( path ):
    ""
    if path and not os.path.isdir( path ):
        os.mkdir( path )


class Configuration:
    """
    The manifests describe repo groupings and the repo layouts for each.

    The remote maps a repository name to the upstream repo URL.

    The local maps a repository name to the local repo directory path.
    """

    def __init__(self):
        ""
        self.topdir = None
        self.upstream = None  # magic: eventually contain the upstream specification
        self.mfest = Manifests()
        self.remote = RepoMap()
        self.local = RepoMap()

    def getRemoteMap(self):
        ""
        return self.remote

    def getManifests(self):
        ""
        return self.mfest

    def computeLocalRepoMap(self):
        ""
        grp = self.mfest.getDefaultGroup()

        if grp != None:
            for spec in grp.getRepoList():
                self.local.setRepoLocation( spec['repo'], path=spec['path'] )

    def setTopLevel(self, directory):
        ""
        self.topdir = directory

    def getTopLevel(self):
        ""
        return self.topdir

    def getLocalRepoPaths(self):
        ""
        paths = []

        grp = self.mfest.getDefaultGroup()
        if grp != None:
            for spec in grp.getRepoList():
                paths.append( spec['path'] )

        return paths

    def getRemoteRepoList(self):
        ""
        repolist = []

        grp = self.mfest.getDefaultGroup()

        if grp != None:
            for spec in grp.getRepoList():
                url = self.remote.getRepoURL( spec['repo'] )
                path = spec['path']
                repolist.append( [ url, path ] )

        return repolist

    def commitLocalRepoMap(self):
        ""
        mrgit = pjoin( self.topdir, '.mrgit' )
        git = gititf.GitRepo( mrgit )
        checkout_repo_map_branch( git )

        try:
            write_mrgit_repo_map_file( self.local, git )
        finally:
            git.checkout_branch( 'master' )

    def createMRGitRepo(self):
        ""
        repodir = pjoin( self.topdir, '.mrgit' )

        git = init_mrgit_repo( repodir )

        write_mrgit_manifests_file( self.mfest, git )

        self.commitLocalRepoMap()


class Manifests:

    def __init__(self):
        ""
        self.groups = []  # order matters - the first group is the default

    def addRepo(self, groupname, reponame, path):
        ""
        grp = self.findGroup( groupname )
        if grp == None:
            grp = RepoGroup( groupname )
            self.groups.append( grp )
        grp.setRepo( reponame, path )

    def getDefaultGroup(self):
        ""
        if len( self.groups ) > 0:
            return self.groups[0]
        return None

    def findGroup(self, groupname):
        ""
        grp = None

        for igrp in self.groups:
            if igrp.getName() == groupname:
                grp = igrp
                break

        return grp

    def writeToFile(self, filename):
        ""
        with open( filename, 'wt' ) as fp:
            for grp in self.groups:
                fp.write( '[ group '+grp.getName()+' ]\n' )
                for spec in grp.getRepoList():
                    fp.write( '    repo='+spec['repo'] )
                    fp.write( ', path='+spec['path'] )
                    fp.write( '\n' )

                fp.write( '\n' )

    def readFromFile(self, filename):
        ""
        with open( filename, 'rt' ) as fp:

            groupname = None

            for line in fp:
                line = line.strip()
                if line.startswith( '#' ):
                    pass
                elif line.startswith( '[' ):
                    groupname = self._parse_group_name( line )
                elif groupname != None:
                    attrs = parse_attribute_line( line )
                    if 'repo' in attrs and 'path' in attrs:
                        self.addRepo( groupname, attrs['repo'], attrs['path'] )

    def _parse_group_name(self, line):
        ""
        groupname = None

        sL = line.strip('[').strip(']').strip().split()
        if len(sL) > 0 and sL[0] == 'group':
            if len(sL) > 1:
                groupname = sL[1]
            else:
                groupname = ''

        return groupname


class RepoGroup:

    def __init__(self, groupname):
        ""
        self.name = groupname
        self.repos = []

    def getName(self):
        ""
        return self.name

    def getRepoList(self):
        ""
        return self.repos

    def setRepo(self, reponame, path):
        ""
        spec = self.findRepo( reponame )
        if spec == None:
            spec = { 'repo':reponame }
            self.repos.append( spec )
        spec['path'] = path

    def findRepo(self, reponame):
        ""
        for spec in self.repos:
            if spec['repo'] == reponame:
                return spec

        return None

    def getRepoNames(self):
        ""
        nameL = [ spec['repo'] for spec in self.repos ]
        return nameL

    def getRepoPath(self, reponame):
        ""
        spec = self.findRepo( reponame )
        return spec['path']


class RepoMap:

    def __init__(self):
        ""
        self.repomap = {}

    def setRepoLocation(self, reponame, url=None, path=None):
        ""
        self.repomap[ reponame ] = ( url, path )

    def getRepoURL(self, reponame):
        ""
        return self.repomap[ reponame ][0]

    def writeToFile(self, filename):
        ""
        with open( filename, 'wt' ) as fp:
            for name,loc in self.repomap.items():
                fp.write( 'repo='+name )
                if loc[0]:
                    fp.write( ', url='+loc[0] )
                if loc[1]:
                    fp.write( ', path='+loc[1] )
                fp.write( '\n' )

            fp.write( '\n' )

    def readFromFile(self, filename, baseurl=None):
        ""
        with open( filename, 'rt' ) as fp:

            for line in fp:
                line = line.strip()

                if line.startswith('#'):
                    pass

                elif line:
                    attrs = parse_attribute_line( line )
                    if 'repo' in attrs:
                        if 'url' in attrs:
                            url = attrs['url']
                        else:
                            url = append_path_to_url( baseurl, attrs['path'] )

                        self.setRepoLocation( attrs['repo'], url=url )


def append_path_to_url( url, path ):
    ""
    url = url.rstrip('/').rstrip(os.sep)
    path = normpath( path )

    if not path or path == '.':
        return url
    else:
        assert not path.startswith('..')
        return pjoin( url, path )


def parse_attribute_line( line ):
    ""
    attrs = {}

    kvL = [ s.strip() for s in line.split(',') ]
    for kvstr in kvL:
        kv = [ s.strip() for s in kvstr.split( '=', 1 ) ]
        if len(kv) == 2 and kv[0]:
            attrs[ kv[0] ] = kv[1]

    return attrs


def read_mrgit_manifests_file( manifests, toplevel ):
    ""
    git = gititf.GitRepo( toplevel+'/.mrgit' )

    git.checkout_branch( 'master' )

    fn = pjoin( git.get_toplevel(), MANIFESTS_FILENAME )
    manifests.readFromFile( fn )


def init_mrgit_repo( repodir ):
    ""
    git = gititf.create_repo( repodir, verbose=3 )

    fn = pjoin( repodir, 'README.txt' )
    with open( fn, 'wt' ) as fp:
        fp.write( 'This directory managed by the mrgit program.\n' )

    git.add( 'README.txt' )
    git.commit( 'initialize mrgit' )

    return git


def write_mrgit_manifests_file( manifests, git ):
    ""
    fn = pjoin( git.get_toplevel(), MANIFESTS_FILENAME )

    git.checkout_branch( 'master' )

    manifests.writeToFile( fn )
    git.add( MANIFESTS_FILENAME )
    git.commit( 'set '+MANIFESTS_FILENAME )


def read_mrgit_repo_map_file( repomap, baseurl, git ):
    ""
    git.checkout_branch( REPOMAP_BRANCH )

    try:
        with change_directory( git.get_toplevel() ):
            repomap.readFromFile( REPOMAP_FILENAME, baseurl )
    finally:
        git.checkout_branch( 'master' )


def read_genesis_map_file( repomap, git ):
    ""
    fn = pjoin( git.get_toplevel(), GENESIS_FILENAME )

    git.checkout_branch( 'master' )

    with change_directory( git.get_toplevel() ):
        repomap.readFromFile( GENESIS_FILENAME )


def write_mrgit_repo_map_file( repomap, git ):
    ""
    with change_directory( git.get_toplevel() ):

        if os.path.exists( REPOMAP_FILENAME ):
            repomap.writeToFile( REPOMAP_TEMPFILE )
            commit_repo_map_file_if_changed( git )

        else:
            repomap.writeToFile( REPOMAP_FILENAME )
            git.add( REPOMAP_FILENAME )
            git.commit( 'init '+REPOMAP_FILENAME )


def commit_repo_map_file_if_changed( git ):
    ""
    if filecmp.cmp( REPOMAP_FILENAME, REPOMAP_TEMPFILE ):
        os.remove( REPOMAP_TEMPFILE )
    else:
        os.rename( REPOMAP_TEMPFILE, REPOMAP_FILENAME )
        git.add( REPOMAP_FILENAME )
        git.commit( 'changed '+REPOMAP_FILENAME )


def checkout_repo_map_branch( git ):
    ""
    if REPOMAP_BRANCH in git.get_branches():
        git.checkout_branch( REPOMAP_BRANCH )
    else:
        git.create_branch( REPOMAP_BRANCH )


def print3( *args ):
    ""
    sys.stdout.write( ' '.join( [ str(arg) for arg in args ] ) + '\n' )
    sys.stdout.flush()
