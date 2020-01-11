#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import re

############################################################################

class Platform:

    def __init__(self, vvtesthome, optdict):
        ""
        self.vvtesthome = vvtesthome
        self.optdict = optdict

        self.maxprocs = 1
        self.nprocs = 1
        self.procpool = ResourcePool( self.nprocs )

        self.platname = None
        self.cplrname = None

        self.envD = {}
        self.attrs = {}

        self.batchspec = None

    # ----------------------------------------------------------------

    def getName(self):  return self.platname
    def getCompiler(self): return self.cplrname
    def getOptions(self): return self.optdict
    def getMaxProcs(self): return self.maxprocs
    def getNumProcs(self): return self.nprocs

    def display(self, isbatched=False):
        ""
        s = "Platform " + self.platname
        if not isbatched:
            if self.nprocs > 0:
                s += ", num procs = " + str(self.nprocs)
            s += ", max procs = " + str(self.maxprocs)
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

    def initProcs(self, set_num, set_max):
        """
        Determines the number of processors and the maximum number for the
        current platform.

        For max procs:
            1. Use 'set_max' if not None
            2. The "maxprocs" attribute if set by the platform plugin
            3. Try to probe the system
            4. The value one if all else fails

        For num procs:
            1. Use 'set_num' if not None
            2. The value of max procs

        This function should not be called for batch mode.
        """
        if set_max == None:
            mx = self.attrs.get( 'maxprocs', None )
            if mx == None:
                if self.batchspec != None:
                    mx = 2**31 - 1  # by default, no limit for batch systems
                else:
                    mx = probe_max_processors()
            self.maxprocs = mx if mx != None else 1
        else:
            self.maxprocs = set_max

        if set_num == None:
            self.nprocs = self.maxprocs
        else:
            self.nprocs = set_num

        if '--qsub-id' in self.optdict:
            self.procpool = ResourcePool( 1 )
        else:
            self.procpool = ResourcePool( self.nprocs )

    def queryProcs(self, np):
        ""
        return self.procpool.available( np )

    def obtainProcs(self, np):
        """
        """
        if np <= 0: np = 1

        procs = self.procpool.get( np )

        job_info = construct_job_info( procs, self.nprocs, self.maxprocs,
                                       self.getattr( 'mpifile', '' ),
                                       self.getattr( 'mpiopts', '' ) )

        return job_info

    def giveProcs(self, job_info):
        """
        """
        self.procpool.put( job_info.procs )

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


class ResourcePool:

    def __init__(self, total):
        ""
        self.total = total
        self.idx = 0
        self.pool = []

    def available(self, num):
        ""
        num = max( num, 1 )
        avail = self._get_num_available()
        return num <= avail

    def get(self, num):
        ""
        num = max( num, 1 )

        items = []

        while len(items) < num and len(self.pool) > 0:
            items.append( self.pool.pop(0) )

        while len(items) < num and self.idx < self.total:
            items.append( self.idx )
            self.idx += 1

        if len(items) < num:
            n = num-len(items)
            for i in range(n):
                items.append( i%self.total )

        return items

    def put(self, items):
        ""
        pset = set( self.pool )
        for i in items:
            if i not in pset:
                pset.add( i )
                self.pool.append( i )
        self.pool.sort()

    def _get_num_available(self):
        ""
        n = len( self.pool )
        n += ( self.total - self.idx )
        return n


def create_Platform_instance( vvtestdir, platname, isbatched, platopts, usenv,
                              numprocs, maxprocs,
                              onopts, offopts,
                              qsubid ):
    """
    This function is an adaptor around construct_Platform(), which passes
    through the command line arguments as a dictionary.  This design is
    ugly but changing it requires interface changes.
    """
    optdict = {}
    if platname:         optdict['--plat']    = platname
    if platopts:         optdict['--platopt'] = platopts
    if usenv:            optdict['-e']        = True
    if numprocs != None: optdict['-n']        = numprocs
    if maxprocs != None: optdict['-N']        = maxprocs
    if onopts:           optdict['-o']        = onopts
    if offopts:          optdict['-O']        = offopts
    if qsubid != None:   optdict['--qsub-id'] = qsubid

    return construct_Platform( vvtestdir, optdict, isbatched=isbatched )


def construct_Platform( vvtestdir, optdict, **kwargs ):
    """
    This function constructs a Platform object, determines the platform &
    compiler, and loads the platform plugin.
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

    if kwargs.get( 'isbatched', False ):
        # this may get overridden by platform_plugin.py
        plat.setBatchSystem( 'procbatch', 1 )

    initialize_platform( plat )

    plat.initProcs( optdict.get( '-n', None ),
                    optdict.get( '-N', None ) )

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
            platname = os.uname()[0]

    if not cplrname:
        if idplatform != None and hasattr( idplatform, "compiler" ):
            cplrname = idplatform.compiler( platname, optdict )
        if not cplrname:
            cplrname = 'gcc'

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
        self.mpi_opts = ''


def construct_job_info( procs, numprocs, maxprocs, mpifile, mpiopts ):
    ""
    job_info = JobInfo( procs, maxprocs )

    if mpifile == 'hostfile':
        # use OpenMPI style machine file
        job_info.mpi_opts = "--hostfile machinefile"
        slots = min( len(procs), numprocs )
        job_info.machinefile = \
                    os.uname()[1].strip() + " slots=" + str(slots) + '\n'

    elif mpifile == 'machinefile':
        # use MPICH style machine file
        job_info.mpi_opts = "-machinefile machinefile"
        job_info.machinefile = ''
        for i in range(len(procs)):
            job_info.machinefile += machine + '\n'

    if mpiopts:
        job_info.mpi_opts += ' ' + mpiopts

    return job_info


def probe_max_processors():
    """
    Tries to determine the number of processors on the current machine.  On
    Linux systems, it uses /proc/cpuinfo.  On OSX systems, it uses sysctl.
    Returns the max, or None if the probe failed.
    """
    mx = None
    
    if os.uname()[0].startswith( 'Darwin' ):
        # try to use sysctl on Macs
        try:
            fp = os.popen( 'sysctl -n hw.physicalcpu 2>/dev/null' )
            s = fp.read().strip()
            fp.close()
            mx = int(s)
        except:
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
        except:
            mx = None

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
