#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import platform

from . import rpool
from . import rprobe


class Platform:

    def __init__(self, platname, mode='direct',
                                 cplrname=None,
                                 environ={},
                                 attrs={},
                                 batchspec=None):
        ""
        self.platname = platname
        self.cplrname = cplrname
        self.mode = mode

        self.envD = environ
        self.attrs = attrs
        self.batchspec = batchspec

        self.procpool = rpool.ResourcePool( 1, 1 )
        self.devicepool = None

    # ----------------------------------------------------------------

    def getName(self):  return self.platname
    def getCompiler(self): return self.cplrname

    def getMaxSize(self):
        ""
        maxnp = self.procpool.maxAvailable()
        if self.devicepool is not None:
            maxnd = self.devicepool.maxAvailable()
        else:
            maxnd = 0
        return (maxnp,maxnd)

    def getSize(self):
        ""
        np = self.procpool.numTotal()
        if self.devicepool is not None:
            nd = self.devicepool.numTotal()
        else:
            nd = 0
        return (np,nd)

    def getNodeSize(self):
        ""
        if self.batchspec is None or self.batchspec[0] == 'procbatch':
            return self.getMaxSize()[0]
        else:
            return self.batchspec[1]

    def display(self):
        ""
        s = "Platform " + self.platname
        if self.mode == 'batch':
            s += ', batch system='+str(self.batchspec[0])
            s += ', ppn='+str(self.batchspec[1])
        else:
            np,nd = self.getSize()
            maxnp,maxnd = self.getMaxSize()
            s += ", num procs = " + str(np)
            s += ", max procs = " + str(maxnp)
            if self.devicepool is not None:
                s += ', num devices = '+str(nd)
                s += ', max devices = '+str(maxnd)
        print ( s )

    def getEnvironment(self):
        """
        Returns a dictionary of environment variables and their values.
        """
        return self.envD

    # ----------------------------------------------------------------

    def getattr(self, name, *default):
        ""
        if len(default) > 0:
            return self.attrs.get( name, default[0] )
        else:
            return self.attrs[name]

    def initializeBatchSystem(self, batchitf):
        ""
        for n,v in self.attrs.items():
            batchitf.setAttr( n, v )

        if self.batchspec:
            qtype,ppn,kwargs = self.batchspec
            batchitf.setQueueType( qtype, ppn, **kwargs )

        for n,v in self.envD.items():
            batchitf.setEnviron( n, v )

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
        np,maxnp = \
            determine_processor_cores( num_procs,
                                       max_procs,
                                       self.attrs.get( 'maxprocs', None ),
                                       use_probe=self.mode != 'batch' )

        nd,maxdev = \
            determine_device_count( num_devices,
                                    max_devices,
                                    self.attrs.get( 'maxdevices', None ) )

        self.procpool = rpool.ResourcePool( np, maxnp )

        if nd is not None:
            assert maxdev is not None
            self.devicepool = rpool.ResourcePool( nd, maxdev )

        if self.mode == 'batch' and self.batchspec is None:
            if not maxnp:
                maxnp = rprobe.probe_num_processors( 4 )
            np = self.attrs.get( 'ppn', self.attrs.get( 'processors_per_node', maxnp ) )
            nd = self.attrs.get( 'dpn', self.attrs.get( 'devices_per_node', maxdev ) )
            self.batchspec = ( 'procbatch', np, {} )
            self.attrs['ppn'] = np
            self.attrs['dpn'] = nd

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


def determine_processor_cores( num_procs, max_procs, plugin_max, use_probe=True ):
    ""
    if max_procs is None:
        if plugin_max is None and use_probe:
            mx = rprobe.probe_num_processors( 4 )
        else:
            mx = plugin_max
    else:
        mx = max_procs

    if num_procs is None:
        np = mx
    else:
        np = num_procs

    return np,mx


def determine_device_count( num_devices, max_devices, plugin_max ):
    ""
    if max_devices is None:
        mx = plugin_max
    else:
        mx = max_devices

    if num_devices is None:
        nd = mx
    else:
        nd = num_devices
        if mx is None:
            # could probe for devices to get a better max
            mx = num_devices

    return nd,mx


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
