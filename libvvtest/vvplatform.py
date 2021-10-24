#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import re
import platform

############################################################################

class Platform:

    def __init__(self, vvtesthome, optdict):
        ""
        self.vvtesthome = vvtesthome
        self.optdict = optdict

        self.plugin_maxprocs = None
        self.procpool = ResourcePool( 1, 1 )
        self.devicepool = None

        self.platname = None
        self.cplrname = None

        self.envD = {}
        self.attrs = {}

        self.batchspec = None

    # ----------------------------------------------------------------

    def getName(self):  return self.platname
    def getCompiler(self): return self.cplrname
    def getOptions(self): return self.optdict

    def getMaxSize(self):
        ""
        maxnp = self.procpool.maxAvailable()
        if self.devicepool != None:
            maxnd = self.devicepool.maxAvailable()
        else:
            maxnd = 0
        return (maxnp,maxnd)

    def getSize(self):
        ""
        np = self.procpool.numTotal()
        if self.devicepool != None:
            nd = self.devicepool.numTotal()
        else:
            nd = 0
        return (np,nd)

    def getPluginMaxProcs(self):
        ""
        return self.plugin_maxprocs

    def display(self, isbatched=False):
        ""
        s = "Platform " + self.platname
        if not isbatched:
            np,nd = self.getSize()
            maxnp,maxnd = self.getMaxSize()
            s += ", num procs = " + str(np)
            s += ", max procs = " + str(maxnp)
            if self.devicepool != None:
                s += ', num devices = '+str(nd)
                s += ', max devices = '+str(maxnd)
        print3( s )

    def getEnvironment(self):
        """
        Returns a dictionary of environment variables and their values.
        """
        return self.envD

    # ----------------------------------------------------------------

    def setenv(self, name, value):
        """
        """
        if value == None:
            if name in self.envD:
                del self.envD[name]
        else:
            self.envD[name] = value

    def setattr(self, name, value):
        """
        """
        if value == None:
            if name in self.attrs:
                del self.attrs[name]
        else:
            self.attrs[name] = value

    def getattr(self, name, *default):
        ""
        if len(default) > 0:
            return self.attrs.get( name, default[0] )
        else:
            return self.attrs[name]

    def setBatchSystem(self, batch, ppn, **kwargs ):
        ""
        assert ppn and ppn > 0

        self.batchspec = ( batch, ppn, kwargs )

    def initializeBatchSystem(self, batchitf):
        ""
        if self.batchspec:
            qtype,ppn,kwargs = self.batchspec
            batchitf.setQueueType( qtype, ppn, **kwargs )

        for n,v in self.envD.items():
            batchitf.setEnviron( n, v )

        for n,v in self.attrs.items():
            batchitf.setAttr( n, v )

    def getDefaultQsubLimit(self):
        ""
        n = self.attrs.get( 'maxsubs', 5 )
        return n

    def initProcs(self, num_procs, max_procs, num_devices, max_devices ):
        """
        Determine and set the number of CPU cores and devices.  The arguments
        are from the command line:

            num_procs   is -n
            num_devices is --devices
            max_procs   is -N
            max_devices is --max-devices
        """
        self.plugin_maxprocs = self.attrs.get( 'maxprocs', None )

        np,maxnp = \
            determine_processor_cores( num_procs,
                                       max_procs,
                                       self.plugin_maxprocs )

        nd,maxdev = \
            determine_device_count( num_devices,
                                    max_devices,
                                    self.attrs.get( 'maxdevices', None ) )

        self.procpool = ResourcePool( np, maxnp )

        if nd != None:
            assert maxdev != None
            self.devicepool = ResourcePool( nd, maxdev )

    def sizeAvailable(self):
        ""
        sznp = self.procpool.numAvailable()
        if self.devicepool == None:
            return ( sznp, 0 )
        else:
            return ( sznp, self.devicepool.numAvailable() )

    def getResources(self, size):
        ""
        np,ndevice = size

        procs = self.procpool.get( np )

        if self.devicepool == None or ndevice == None:
            devices = None
        else:
            devices = self.devicepool.get( max( 0, int(ndevice) ) )

        job_info = construct_job_info( procs, self.procpool,
                                       devices, self.devicepool,
                                       self.getattr( 'mpifile', '' ),
                                       self.getattr( 'mpiopts', '' ) )

        return job_info

    def returnResources(self, job_info):
        ""
        self.procpool.put( job_info.procs )
        if self.devicepool != None and job_info.devices != None:
            self.devicepool.put( job_info.devices )

    # ----------------------------------------------------------------

    def testingDirectory(self):
        """
        """
        if 'TESTING_DIRECTORY' in os.environ:
            return os.environ['TESTING_DIRECTORY']

        elif 'testingdir' in self.attrs:
            return self.attrs['testingdir']

        return None

    def which(self, prog):
        """
        """
        if not prog:
          return None
        if os.path.isabs(prog):
          return prog
        for d in os.environ['PATH'].split(':'):
          if not d: d = '.'
          if os.path.isdir(d):
            f = os.path.join( d, prog )
            if os.path.exists(f) and \
               os.access(f,os.R_OK) and os.access(f,os.X_OK):
              if not os.path.isabs(f):
                f = os.path.abspath(f)
              return os.path.normpath(f)
        return None


def determine_processor_cores( num_procs, max_procs, plugin_max ):
    ""
    if max_procs == None:
        if plugin_max == None:
            mx = probe_max_processors( 4 )
        else:
            mx = plugin_max
    else:
        mx = max_procs

    if num_procs == None:
        np = mx
    else:
        np = num_procs

    return np,mx


def determine_device_count( num_devices, max_devices, plugin_max ):
    ""
    if max_devices == None:
        mx = plugin_max
    else:
        mx = max_devices

    if num_devices == None:
        nd = mx
    else:
        nd = num_devices
        if mx == None:
            # could probe for devices to get a better max
            mx = num_devices

    return nd,mx


class ResourcePool:

    def __init__(self, total, maxavail):
        ""
        self.total = total
        self.maxavail = maxavail

        self.pool = None  # maps hardware id to num available

    def maxAvailable(self):
        ""
        return self.maxavail

    def numTotal(self):
        ""
        return self.total

    def numAvailable(self):
        ""
        if self.pool == None:
            num = self.total
        else:
            num = 0
            for cnt in self.pool.values():
                num += max( 0, cnt )

        return num

    def get(self, num):
        ""
        items = []

        if num > 0:

            if self.pool == None:
                self._initialize_pool()

            while len(items) < num:
                self._get_most_available( items, num )

        return items

    def put(self, items):
        ""
        for idx in items:
            self.pool[idx] = ( self.pool[idx] + 1 )

    def _get_most_available(self, items, num):
        ""
        # reverse the index in the sort list (want indexes to be ascending)
        L = [ (cnt,self.maxavail-idx) for idx,cnt in self.pool.items() ]
        L.sort( reverse=True )

        for cnt,ridx in L:
            idx = self.maxavail - ridx
            items.append( idx )
            self.pool[idx] = ( self.pool[idx] - 1 )
            if len(items) == num:
                break

    def _initialize_pool(self):
        ""
        self.pool = {}

        for i in range(self.total):
            idx = i%(self.maxavail)
            self.pool[idx] = self.pool.get( idx, 0 ) + 1


def create_Platform_instance( vvtestdir, platname, isbatched, platopts, usenv,
                              numprocs, maxprocs, devices, max_devices,
                              onopts, offopts ):
    """
    This function is an adaptor around construct_Platform(), which passes
    through the command line arguments as a dictionary.
    """
    optdict = {}
    if platname:         optdict['--plat']    = platname
    if platopts:         optdict['--platopt'] = platopts
    if usenv:            optdict['-e']        = True
    if numprocs != None: optdict['-n']        = numprocs
    if maxprocs != None: optdict['-N']        = maxprocs
    if onopts:           optdict['-o']        = onopts
    if offopts:          optdict['-O']        = offopts

    return construct_Platform( vvtestdir, optdict,
                               isbatched=isbatched,
                               devices=devices,
                               max_devices=max_devices )


def construct_Platform( vvtestdir, optdict, **kwargs ):
    """
    This function constructs a Platform object, determines the platform &
    compiler, and loads the platform plugin.

    It is retained for backward compatibility for now.  A script written by
    a project team called this function to set environment variables in the
    platform plugin and called certain methods on the resulting Platform object.

    I want to get rid of that usage, but I'd like to abstract out the use
    case and satisfy it in a better way (one that does not mean poking into
    the internals of vvtest).
    """
    assert vvtestdir
    assert os.path.exists( vvtestdir )
    assert os.path.isdir( vvtestdir )

    plat = Platform( vvtestdir, optdict )

    platname,cplrname = get_platform_and_compiler(
                                optdict.get( '--plat', None ),
                                optdict.get( '--cplr', None ),
                                optdict.get( '-o', [] ),
                                optdict.get( '-O', [] ) )

    plat.platname = platname
    plat.cplrname = cplrname

    set_platform_options( plat, optdict.get( '--platopt', {} ) )

    isbatched = kwargs.get( 'isbatched', False )
    if isbatched:
        # this may get overridden by platform_plugin.py
        plat.setBatchSystem( 'procbatch', 1 )

    initialize_platform( plat )

    plat.initProcs( optdict.get( '-n', None ),
                    optdict.get( '-N', None ),
                    kwargs.get( 'devices', None ),
                    kwargs.get( 'max_devices', None ) )

    return plat


def set_platform_options( plat, platopts ):
    ""
    q = platopts.get( 'queue', platopts.get( 'q', None ) )
    plat.setattr( 'queue', q )

    act = platopts.get( 'account', platopts.get( 'PT', None ) )
    plat.setattr( 'account', act )

    wall = platopts.get( 'walltime', None )
    plat.setattr( 'walltime', wall )

    # QoS = "Quality of Service" e.g. "normal", "long", etc.
    QoS = platopts.get( 'QoS', None )
    plat.setattr( 'QoS', QoS )


def get_platform_and_compiler( platname, cplrname, onopts, offopts ):
    ""
    idplatform = import_idplatform()

    optdict = convert_to_option_dictionary( platname, cplrname, onopts, offopts )

    if not platname:
        if idplatform != None and hasattr( idplatform, "platform" ):
            platname = idplatform.platform( optdict )
        if not platname:
            platname = platform.uname()[0]

    if not cplrname:
        if idplatform != None and hasattr( idplatform, "compiler" ):
            cplrname = idplatform.compiler( platname, optdict )

    return platname, cplrname


def initialize_platform( plat ):
    ""
    plug = import_platform_plugin()

    if plug != None and hasattr( plug, 'initialize' ):
        plug.initialize( plat )


def import_idplatform():
    ""
    try:
        # this comes from the config directory
        import idplatform
    except ImportError:
        idplatform = None

    return idplatform


def import_platform_plugin():
    ""
    try:
        # this comes from the config directory
        import platform_plugin
    except ImportError:
        platform_plugin = None

    return platform_plugin


def convert_to_option_dictionary( platname, cplrname, onopts, offopts ):
    ""
    optdict = {}

    if platname: optdict['--plat'] = platname
    if cplrname: optdict['--cplr'] = cplrname

    optdict['-o'] = onopts
    optdict['-O'] = offopts

    return optdict


##########################################################################

class JobInfo:
    """
    This object is used to communicate and hold information for a job
    processor request, including a string to give to the mpirun command, if
    any.  It is returned to the Platform when the job finishes.
    """
    def __init__(self, procs, maxprocs):
        ""
        self.procs = procs
        self.maxprocs = maxprocs
        self.devices = None
        self.maxdevices = None
        self.mpi_opts = ''


def construct_job_info( procs, procpool,
                        devices, devicepool,
                        mpifile, mpiopts ):
    ""
    numprocs = procpool.numTotal()
    maxprocs = procpool.maxAvailable()

    job_info = JobInfo( procs, maxprocs )

    if devices != None:
        job_info.devices = devices
        job_info.maxdevices = devicepool.maxAvailable()

    if mpifile == 'hostfile':
        # use OpenMPI style machine file
        job_info.mpi_opts = "--hostfile machinefile"
        slots = min( len(procs), numprocs )
        job_info.machinefile = \
                    platform.uname()[1].strip() + " slots=" + str(slots) + '\n'

    elif mpifile == 'machinefile':
        # use MPICH style machine file
        job_info.mpi_opts = "-machinefile machinefile"
        job_info.machinefile = ''
        for i in range(len(procs)):
            job_info.machinefile += machine + '\n'

    if mpiopts:
        job_info.mpi_opts += ' ' + mpiopts

    return job_info


def probe_max_processors( fail_value=4 ):
    """
    Tries to determine the number of processors on the current machine.  On
    Linux systems, it uses /proc/cpuinfo.  On OSX systems, it uses sysctl.
    """
    mx = None
    
    if platform.uname()[0].startswith( 'Darwin' ):
        # try to use sysctl on Macs
        try:
            fp = os.popen( 'sysctl -n hw.physicalcpu 2>/dev/null' )
            s = fp.read().strip()
            fp.close()
            mx = int(s)
        except Exception:
            mx = None
    
    if mx == None and os.path.exists( '/proc/cpuinfo' ):
        # try to probe the number of available processors by
        # looking at the proc file system
        repat = re.compile( 'processor\s*:' )
        mx = 0
        try:
            fp = open( '/proc/cpuinfo', 'r' )
            for line in fp.readlines():
                if repat.match(line) != None:
                    mx += 1
            fp.close()
        except Exception:
            mx = None

    if not mx or mx < 1:
        mx = fail_value

    return mx


##########################################################################

# determine the directory containing the current file
mydir = None
if __name__ == "__main__":
  mydir = os.path.abspath( sys.path[0] )
else:
  mydir = os.path.dirname( os.path.abspath( __file__ ) )


def print3( *args ):
    sys.stdout.write( ' '.join( [ str(arg) for arg in args ] ) + '\n' )
    sys.stdout.flush()

###############################################################################

if __name__ == "__main__":
    """
    """
    vvtestdir = os.path.dirname(mydir)
    sys.path.insert( 1, os.path.join( vvtestdir, 'config' ) )
    plat = construct_Platform( vvtestdir, {} )
    plat.display()
