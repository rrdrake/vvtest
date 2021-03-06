#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import getopt
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


def init_cmd( argv, **kwargs ):
    ""
    cfg = Configuration()
    cfg.setTopLevel( os.getcwd() )
    cfg.setManifestName( '' )
    make_mrgit_repo( cfg )
    cfg.commitLocalRepoMap()


def clone_cmd( argv, **kwargs ):
    ""
    optL,argL = getopt.getopt( argv, 'Gvm:', [] )

    optD = {}
    for n,v in optL:
        if n == '-v':
            cnt = optD.get( '-v', 0 )
            optD[n] = cnt+1
        else:
            optD[n] = v

    verb = optD.get( '-v', kwargs.get( 'verbose', 0 ) ) + 1

    augment_clone_command_line( optD, argL, os.environ )

    if len( argL ) == 0:
        errorexit( 'You must specify a repository to clone.' )

    creator = CloneCreator( optD.get( '-m', None ), verbose=verb )
    creator.clone( argL, '-G' in optD )


def augment_clone_command_line( opts, arglist, environ ):
    ""
    if len( arglist ) == 0:
        if 'REPO_MANIFEST_URL' in environ:
            url = environ['REPO_MANIFEST_URL'].strip()
            if url:
                arglist.append( url )
                opts['-G'] = ''


def get_verbosity( argv, kwargs, default ):
    ""
    verb = 0

    if '-v' in argv:
        verb = argv.count( '-v' )
        verb += 2*argv.count( '-vv' )
    elif '-vv' in argv:
        verb = 2*argv.count( '-vv' )

    if not verb:
        verb = kwargs.get( 'verbose', default )

    # reserve the value zero for "quiet" (not implemented yet)
    verb += 1

    return verb


def pull_cmd( argv, **kwargs ):
    ""
    verb = get_verbosity( argv, kwargs, 2 )

    cfg = load_configuration()

    top = cfg.getTopLevel()
    for name,path in cfg.getLocalRepoPaths():
        git = gititf.GitRepo( pjoin( top, path ) )
        git.run( 'pull', verbose=verb )


def add_cmd( argv, **kwargs ):
    ""
    verb = get_verbosity( argv, kwargs, 2 )

    cfg = load_configuration()

    top = cfg.getTopLevel()
    for name,path in cfg.getLocalRepoPaths():
        git = gititf.GitRepo( pjoin( top, path ) )
        args = [ pipes.quote(arg) for arg in argv ]
        git.run( 'add', *args, verbose=verb )


def status_cmd( argv, **kwargs ):
    ""
    verb = get_verbosity( argv, kwargs, 0 )

    cfg = load_configuration()

    top = cfg.getTopLevel()
    stats = StatusWriter( verb )
    for name,path in cfg.getLocalRepoPaths():
        statD = get_repo_status( name, pjoin( top, path ), verb )
        stats.add( name, path, statD )
    stats.write( sys.stdout )


def run_cmd( argv, **kwargs ):
    ""
    verb = get_verbosity( argv, kwargs, 0 )

    cfg = load_configuration()

    top = cfg.getTopLevel()
    for name,path in cfg.getLocalRepoPaths():
        git = gititf.GitRepo( pjoin( top, path ) )
        if verb > 0:
            print3( '\nRepository', repr(name), 'in path', repr(path), '...' )
        cmd = ' '.join( [ pipes.quote(arg) for arg in argv ] )
        x,out = git.run( cmd, verbose=verb, raise_on_error=False )
        if x != 0 and verb < 3:
            print3( out )


def load_configuration():
    ""
    cfg = Configuration()

    top = find_top_level( '.mrgit' )
    if top:
        cfg.setTopLevel( top )
        read_mrgit_manifests_file( cfg.getManifests(), top )
        read_mrgit_config_file( top+'/.mrgit', cfg )

    else:
        top = find_top_level( '.repo' )
        if top:
            cfg.setTopLevel( top )
            gconv = GoogleConverter( top+'/.repo/manifests' )
            gconv.loadManifestsAndRemoteMap( cfg.getManifests(),
                                             cfg.getRemoteMap(),
                                             top )
            set_google_repo_manifest( cfg, top+'/.repo' )

        else:
            errorexit( 'Not an mrgit repository (nor any parent directory)' )

    return cfg


def find_top_level( repodir ):
    ""
    top = None
    stopat = os.environ.get( 'MRGIT_PARENT_SEARCH_BARRIER', '/' )

    d1 = os.getcwd()
    while True:
        if os.path.isdir( pjoin( d1, repodir ) ):
            top = d1
            break
        d2 = dirname( d1 )
        if not d2 or d1 == d2 or os.path.samefile( d1, stopat ):
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


class CloneCreator:

    def __init__(self, groupname=None, verbose=1):
        ""
        self.grpname = groupname
        self.verbose = verbose

    def clone(self, url_list, is_google_manifest=False):
        ""
        urls, directory = parse_url_list( url_list )
        assert len( urls ) > 0

        self.urls = urls
        self.dest = directory

        check_destination_directory( directory )

        self.tmpdir = TempDirectory( self.dest )

        top = self.cloneByUpstreamType( is_google_manifest )

        print3( 'mrgit toplevel is', repr(top) )

        self.tmpdir.rename( top )

    def cloneByUpstreamType(self, is_google_manifest):
        ""
        cfg = Configuration()
        cfg.setTopLevel( self.tmpdir.path() )

        try:
            if is_google_manifest:
                if len(self.urls) != 1:
                    errorexit( 'must specify exactly one URL with the -G option' )
                top = self.fromGoogleManifests( cfg )

            elif len( self.urls ) == 1:
                top = self.fromSingleURL( cfg )

            else:
                top = self.fromURLs( cfg )

        except MRGitExitError:
            self.tmpdir.cleanup()
            raise

        cfg.commitLocalRepoMap()

        set_to_ignore_mrgit_directory( cfg )

        cfg.setTopLevel( top )

        return top

    def fromSingleURL(self, cfg):
        ""
        url = self.urls[0]
        wrkdir = self.tmpdir.path()

        try:
            # prefer a .mrgit repo under the given url
            verb = max( 0, self.verbose - 1 )
            git = temp_clone( url+'/.mrgit', wrkdir, verb )

        except gititf.GitInterfaceError:
            git = None

        if git == None:
            # that failed, so just clone the given url
            try:
                git = temp_clone( url, wrkdir, self.verbose )
            except gititf.GitInterfaceError:
                errorexit( 'failed to clone', url )

        upstream = check_for_mrgit_repo( git )

        if upstream:
            # we just cloned an mrgit or genesis repo

            # move the clone so it becomes the .mrgit directory
            mrgit = wrkdir+'/.mrgit'
            assert not os.path.islink( mrgit ) and not os.path.exists( mrgit )
            os.rename( git.get_toplevel(), mrgit )

            top = self._populate_config_and_mrgit_repo( cfg, upstream )

        elif is_google_manfiests_repo( git.get_toplevel() ):
            # we just cloned a Google manifests repo

            upstream = GoogleConverter( git.get_toplevel() )

            top = self._populate_config_and_mrgit_repo( cfg, upstream )

            dst = pjoin( wrkdir, '.mrgit', 'google_manifests' )
            move_directory_contents( git.get_toplevel(), dst )

        else:
            # not an mrgit, genesis or Google repo, just a generic repository

            if self.grpname != None:
                errorexit( 'cannot specify repo group for a list of URLs' )

            # move the clone to a directory with the name of the upstream URL
            loc = pjoin( wrkdir, gititf.repo_name_from_url( url ) )
            move_directory_contents( git.get_toplevel(), loc )

            upstream = UpstreamURLs( [ url ] )

            top = self._populate_config_and_mrgit_repo( cfg, upstream )

        return top

    def fromURLs(self, cfg):
        ""
        if self.grpname != None:
            errorexit( 'cannot specify repo group for a list of URLs' )

        upstream = UpstreamURLs( self.urls )

        top = self._populate_config_and_mrgit_repo( cfg, upstream )

        return top

    def fromGoogleManifests(self, cfg):
        ""
        wrkdir = self.tmpdir.path()

        git = temp_clone( self.urls[0], wrkdir )

        gconv = GoogleConverter( git.get_toplevel() )

        top = self._populate_config_and_mrgit_repo( cfg, gconv )

        dst = pjoin( wrkdir, '.mrgit', 'google_manifests' )
        move_directory_contents( git.get_toplevel(), dst )

        return top

    def _populate_config_and_mrgit_repo(self, cfg, upstream):
        ""
        top = cfg.getTopLevel()

        cfg.setUpstreamType( upstream.getType() )

        upstream.loadManifestsAndRemoteMap( cfg.getManifests(),
                                            cfg.getRemoteMap(),
                                            top )

        set_config_manifest_name( cfg, self.grpname )

        newtop = compute_top_level_directory( self.dest, cfg,
                                              upstream.remoteName() )

        if os.path.exists( newtop ) and not os.path.samefile( top, newtop ):
            check_nonempty_destination_paths( newtop, cfg.getLocalRepoPaths() )

        clone_repositories_from_config( cfg, self.verbose )

        make_mrgit_repo( cfg, self.verbose )

        return newtop


def check_destination_directory( directory ):
    ""
    if directory and os.path.exists( directory ):
        if os.path.isdir( directory ):
            if len( os.listdir( directory ) ) > 0:
                errorexit( 'destination path exists and is not empty:',
                           repr(directory) )
        else:
            errorexit( 'destination path is not a directory:', repr(directory) )


def check_nonempty_destination_paths( top, pathlist ):
    ""
    dst = top+'/.mrgit'
    if os.path.islink(dst) or os.path.exists(dst):
        errorexit( 'a previous mrgit exists in destination path:', repr(dst) )

    for name,path in pathlist:
        dst = pjoin( top, path )
        if os.path.islink(dst) or os.path.exists(dst):
            errorexit( 'destination path already exists:', repr(dst) )


class MRGitUpstream:

    def __init__(self, url):
        ""
        assert url.endswith( os.path.sep+'.mrgit' )
        self.url = url

    def getType(self):
        ""
        return 'mrgit'

    def remoteName(self):
        ""
        return gititf.repo_name_from_url( dirname( self.url ) )

    def loadManifestsAndRemoteMap(self, mfest, rmap, toplevel):
        ""
        read_mrgit_manifests_file( mfest, toplevel )

        git = gititf.GitRepo( toplevel+'/.mrgit' )
        read_mrgit_repo_map_file( rmap, dirname( self.url ), git )


class GenesisUpstream:

    def __init__(self, url):
        ""
        self.url = url

    def getType(self):
        ""
        return 'genesis'

    def remoteName(self):
        ""
        return gititf.repo_name_from_url( self.url )

    def loadManifestsAndRemoteMap(self, mfest, rmap, toplevel):
        ""
        read_mrgit_manifests_file( mfest, toplevel )

        git = gititf.GitRepo( toplevel+'/.mrgit' )
        read_genesis_map_file( rmap, git )


class UpstreamURLs:

    def __init__(self, url_list):
        ""
        self.urls = url_list

    def getType(self):
        ""
        return 'urls'

    def remoteName(self):
        ""
        return None

    def loadManifestsAndRemoteMap(self, mfest, rmap, toplevel):
        ""
        groupname = ''
        for url in self.urls:
            name = gititf.repo_name_from_url( url )
            mfest.addRepo( groupname, name, name )

        for url in self.urls:
            name = gititf.repo_name_from_url( url )
            rmap.setRepoLocation( name, url=url )


class GoogleConverter:

    def __init__(self, manifests_directory):
        ""
        self.srcdir = manifests_directory

    def getType(self):
        ""
        return 'googlerepo'

    def remoteName(self):
        ""
        return None

    def loadManifestsAndRemoteMap(self, mfest, rmap, toplevel):
        ""
        self.readManifestFiles()
        self.fillManifests( mfest )
        self.fillRepoMap( rmap )

    def fillManifests(self, mfest):
        ""
        grpname = self.getDefaultGroupName()
        self._create_group_from_manifest( self.default, mfest, grpname )

        for gmr in self.manifests:
            self._create_group_from_manifest( gmr, mfest )

    def readManifestFiles(self):
        ""
        fn = pjoin( self.srcdir, 'default.xml' )
        self.default = GoogleManifestReader( fn )
        self.default.createRepoNameToURLMap()

        self.manifests = []
        for fn in glob.glob( pjoin( self.srcdir, '*.xml' ) ):
            if basename(fn) != 'default.xml':
                gmr = GoogleManifestReader( fn )
                gmr.createRepoNameToURLMap()
                self.manifests.append( gmr )

    def fillRepoMap(self, rmap):
        ""
        for gmr in [ self.default ] + self.manifests:
            for reponame in gmr.getRepoNames():
                url = self.getPrimaryURL( reponame )
                rmap.setRepoLocation( reponame, url )

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

    def getDefaultGroupName(self):
        ""
        if 'code' not in self.getGroupNames():
            return 'code'
        else:
            return None

    def getGroupNames(self):
        ""
        names = []

        for gmr in self.manifests:
            if self._all_urls_are_primary( gmr ):
                names.append( gmr.getGroupName() )

        return names

    def _create_group_from_manifest(self, gmr, mfest, force_groupname=None):
        ""
        if self._all_urls_are_primary( gmr ):
            for name,url,path in gmr.getProjectList():
                if force_groupname:
                    groupname = force_groupname
                else:
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
        # put this here instead of the top of this file because reading
        # Google manifests is not core to mrgit
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


def set_google_repo_manifest( cfg, repodir ):
    ""
    lf = pjoin( repodir, 'manifest.xml' )
    fn = basename( os.readlink( lf ) )

    if fn == 'default.xml':
        grpname = cfg.getManifests().getDefaultGroup().getName()
    else:
        grpname = os.path.splitext( fn )[0]

    assert cfg.getManifests().findGroup( grpname ) != None

    cfg.setManifestName( grpname )


def is_google_manfiests_repo( path ):
    ""
    xml = pjoin( path, 'default.xml' )
    if os.path.isfile( xml ):
        try:
            gmr = GoogleManifestReader( xml )
            gmr.createRepoNameToURLMap()
            projL = gmr.getProjectList()
        except Exception:
            pass
        else:
            if len( projL ) > 0:
                name,url,sub = projL[0]
                if name.strip() and url.strip():
                    return True

    return False


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


def set_config_manifest_name( cfg, groupname ):
    ""
    if groupname == None:
        grp = cfg.getManifests().getDefaultGroup()
        if grp != None:
            groupname = grp.getName()
        else:
            groupname = ''
    else:
        grp = cfg.getManifests().findGroup( groupname )
        if grp == None:
            errorexit( 'manifest group name not found:', repr(groupname) )

    cfg.setManifestName( groupname )


def compute_top_level_directory( directory, cfg, remotename ):
    ""
    if directory:
        top = normpath( abspath( directory ) )
    else:
        top = path_for_toplevel( cfg, remotename )

    return top


def path_for_toplevel( cfg, remotename ):
    ""
    grp = cfg.getManifests().findGroup( cfg.getManifestName() )

    if grp == None:
        # only from an empty mrgit init, or a clone of one
        top = abspath( remotename )

    elif grp.getName():
        top = abspath( grp.getName() )

    else:
        # when cloning a repo which is a clone of a list of URLs
        top = abspath( '.' )

    return top


def clone_repositories_from_config( cfg, verbose=2 ):
    ""
    topdir = cfg.getTopLevel()

    check_make_directory( topdir )

    with change_directory( topdir ):
        for url,loc in cfg.getActiveRepoList():
            if not os.path.exists( loc+'/.git' ):
                robust_clone( url, loc, verbose )


def robust_clone( url, into_dir, verbose=2 ):
    ""
    tmp = None

    if verbose > 0:
        verbose = 3

    try:
        if os.path.exists( into_dir ):

            assert '.git' not in os.listdir( into_dir )

            tmp = tempfile.mkdtemp( '', 'mrgit_tempclone_', abspath( into_dir ) )
            gititf.clone_repo( url, tmp, verbose=verbose )
            move_directory_contents( tmp, into_dir )

            git = gititf.GitRepo( into_dir )

        else:
            git = gititf.clone_repo( url, into_dir, verbose=verbose )

    except gititf.GitInterfaceError:
        if tmp:
            shutil.rmtree( tmp )
        raise MRGitExitError( 'clone failed for '+url )

    return git


def temp_clone( url, chdir, verbose=1 ):
    ""
    if verbose > 0:
        verbose = 3

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

    def newDirectory(self):
        ""
        return self.isnew

    def rename(self, todir):
        ""
        if self.isnew:
            move_directory_contents( self.tmpd, todir )

    def cleanup(self):
        ""
        if self.isnew:
            if os.path.exists( self.tmpd ):
                try:
                    shutil.rmtree( self.tmpd )
                except Exception:
                    pass


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
        self.upstream = None
        self.grpname = None

        self.mfest = Manifests()
        self.remote = RepoMap()
        self.inactive = set()

    def setTopLevel(self, directory):
        ""
        self.topdir = directory

    def setUpstreamType(self, upstream):
        ""
        self.upstream = upstream

    def getUpstreamType(self):
        ""
        return self.upstream

    def setManifestName(self, groupname):
        ""
        self.grpname = groupname

    def getManifestName(self):
        ""
        return self.grpname

    def getTopLevel(self):
        ""
        return self.topdir

    def getManifests(self):
        ""
        return self.mfest

    def getRemoteMap(self):
        ""
        return self.remote

    def getLocalRepoPaths(self):
        ""
        paths = []

        grp = self.mfest.findGroup( self.grpname )
        if grp != None:
            for spec in grp.getRepoList():
                paths.append( ( spec['repo'], spec['path'] ) )

        return paths

    def getActiveRepoList(self):
        ""
        repolist = []

        grp = self.mfest.findGroup( self.grpname )

        if grp != None:
            for spec in grp.getRepoList():
                url = self.remote.getRepoURL( spec['repo'] )
                path = spec['path']
                repolist.append( [ url, path ] )

        return repolist

    def commitLocalRepoMap(self):
        ""
        local = RepoMap()

        # magic: need to add all repos to 'local' that are currently cloned
        #        - includes the repos in the current group name
        #        - must also include inactive repos
        if self.grpname == None:
            grp = None
        else:
            grp = self.mfest.findGroup( self.grpname )

        if grp != None:
            for spec in grp.getRepoList():
                local.setRepoLocation( spec['repo'], path=spec['path'] )

        mrgit = pjoin( self.topdir, '.mrgit' )
        git = gititf.GitRepo( mrgit )
        checkout_repo_map_branch( git )

        try:
            write_mrgit_repo_map_file( local, git )
        finally:
            git.checkout_branch( 'master' )


def make_mrgit_repo( cfg, verbose=2):
    ""
    # drop verbosity for internal operations
    verb = max( 0, verbose-1 )

    repodir = pjoin( cfg.getTopLevel(), '.mrgit' )
    mfests = cfg.getManifests()

    if not gititf.is_a_local_repository( repodir ):
        git = init_mrgit_repo( repodir, verb )
        commit_mrgit_manifests_file( mfests, git, verb )
        commit_mrgit_gitignore_file( git, verb )

    write_mrgit_config_file( repodir, cfg )


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
        assert groupname != None

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


def init_mrgit_repo( repodir, verbose=2 ):
    ""
    git = gititf.create_repo( repodir, verbose=verbose )

    fn = pjoin( repodir, 'README.txt' )
    with open( fn, 'wt' ) as fp:
        fp.write( 'This directory managed by mrgit.\n' )

    git.add( 'README.txt' )
    git.commit( 'initialize mrgit' )

    return git


def commit_mrgit_manifests_file( manifests, git, verbose=2 ):
    ""
    fn = pjoin( git.get_toplevel(), MANIFESTS_FILENAME )

    git.checkout_branch( 'master', verbose=verbose )

    manifests.writeToFile( fn )
    git.add( MANIFESTS_FILENAME, verbose=verbose )
    git.commit( 'set '+MANIFESTS_FILENAME, verbose=verbose )


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


def set_to_ignore_mrgit_directory( cfg ):
    ""
    for name,path in cfg.getLocalRepoPaths():
        if path == '.':
            fn = pjoin( cfg.getTopLevel(), '.git', 'info', 'exclude' )
            check_add_mrgit_exclude_line( fn )


def check_add_mrgit_exclude_line( filename ):
    ""
    excl = '/.mrgit'

    addit = True

    if os.path.exists( filename ):
        addit = not file_has_line( filename, excl )

    if addit:
        with open( filename, 'at' ) as fp:
            fp.write( excl+'\n' )


def file_has_line( filename, line ):
    ""
    with open( filename, 'rt' ) as fp:
        for line in fp:
            if line.strip() == line:
                return True

    return False


def get_repo_status( name, path, verbose ):
    ""
    git = gititf.GitRepo( path )

    if verbose > 0:
        if verbose >= 3:
            print3()
        print3( 'Getting status of', repr(name), '...' )

    gitverb = ( 0 if verbose < 3 else 3 )
    statD = git.status( verbose=gitverb )

    return statD


def commit_mrgit_gitignore_file( git, verbose ):
    ""
    with change_directory( git.get_toplevel() ):

        with open( '.gitignore', 'wt' ) as fp:
            fp.write( '/config\n' )

        git.add( '.gitignore', verbose=verbose )
        git.commit( 'set .gitignore', verbose=verbose )


def write_mrgit_config_file( destdir, cfg ):
    ""
    fn = pjoin( destdir, 'config' )

    grpname = cfg.getManifestName()

    with open( fn, 'wt' ) as fp:
        fp.write( '[core]\n' )
        fp.write( '    group = '+grpname+'\n' )

        up = cfg.getUpstreamType()
        if up:
            fp.write( '    upstream = '+up+'\n' )


def read_mrgit_config_file( fromdir, cfg ):
    ""
    fn = pjoin( fromdir, 'config' )

    with open( fn, 'rt' ) as fp:
        section = None
        for line in fp:
            line = line.strip()
            if not line or line.startswith( '#' ):
                pass
            elif line.startswith( '[' ):
                section = _parse_config_section_name( line )
            elif section:
                _parse_config_section_line( section, line, cfg )


def _parse_config_section_line( section, line, cfg ):
    ""
    attrs = parse_attribute_line( line )

    if section[0] == 'core':
        if 'group' in attrs:
            cfg.setManifestName( attrs['group'] )
        if 'upstream' in attrs:
            cfg.setUpstreamType( attrs['upstream'] )


def _parse_config_section_name( line ):
    ""
    val = line.strip('[').split(']',1)[0].strip()
    valL = val.split( None, 1 )
    if len(valL) == 1:
        valL.append( '' )
    return valL


class StatusWriter:

    def __init__(self, verbose=0):
        ""
        self.verbose = verbose
        self.rows = []
        self.files = {}

    def add(self, reponame, path, stats):
        ""
        self.rows.append( ( reponame,
                            str( len( stats['changed'] ) ),
                            str( len( stats['untracked'] ) ),
                            str( len( stats['commits'] ) ),
                            path,
                            str( stats['branch'] ) ) )

        chgL = self._collect_files( path, stats['changed'] )
        unkL = self._collect_files( path, stats['untracked'] )

        self.files[ reponame ] = [ chgL, unkL ]

    def write(self, fileobj):
        ""
        if self.verbose > 1:
            self.writeFileList( fileobj )

        self.writeSummaryTable( fileobj )

        fileobj.flush()

    def writeSummaryTable(self, fileobj):
        ""
        hdr = ( 'name', 'changed', 'untracked', 'commits', 'path', 'branch' )

        szL = [ len(hdr[i]) for i in range(len(hdr)) ]
        for row in self.rows:
            for i in range( len(row) ):
                szL[i] = max( szL[i], len(str(row[i])) )

        fmt = '%%-%ds | %%%ds %%%ds %%%ds | %%-%ds %%-%ds' % tuple(szL)
        hs = fmt % hdr

        hz = '-'*(szL[0]+1) + '+' + \
             '-'*(szL[1]+1) + '-'*(szL[2]+1) + '-'*(szL[3]+2) + '+' + \
             '-'*(szL[4]+1) + '-'*(szL[5]+1)

        fileobj.write( '\n' + hs + '\n' + hz+'\n' )
        for row in self.rows:
            fileobj.write( fmt % row + '\n' )

        fileobj.write( '\n' )

    def writeFileList(self, fileobj):
        ""
        for name,lists in self.files.items():
            chgL,unkL = lists
            if len(chgL) > 0 or len(unkL) > 0:
                fileobj.write( '\nRepository '+name+':\n' )
                self._write_files( '  changed:', chgL, fileobj )
                self._write_files( 'untracked:', unkL, fileobj )

    def _write_files(self, listype, fnames, fileobj):
        ""
        for fn in fnames:
            fileobj.write( '    '+listype+' '+fn+'\n' )

    def _collect_files(self, path, filelist):
        ""
        fL = []
        for fn in filelist:
            fL.append( normpath( pjoin( path, fn ) ) )
        fL.sort()

        return fL


def print3( *args ):
    ""
    sys.stdout.write( ' '.join( [ str(arg) for arg in args ] ) + '\n' )
    sys.stdout.flush()
