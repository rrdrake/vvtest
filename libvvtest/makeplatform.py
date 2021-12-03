#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os
import platform

from .vvplatform import Platform


def create_Platform_instance( vvtestdir, platname, mode, platopts,
                              numprocs, maxprocs, devices, max_devices,
                              onopts, offopts ):
    ""
    assert vvtestdir
    assert os.path.exists( vvtestdir ) and os.path.isdir( vvtestdir )
    assert mode in ['direct','batch','batchjob']

    optdict = {}
    if platname:         optdict['--plat']    = platname
    if platopts:         optdict['--platopt'] = platopts
    if onopts:           optdict['-o']        = onopts
    if offopts:          optdict['-O']        = offopts

    platname,cplrname = determine_platform_and_compiler( platname, onopts, offopts )

    platcfg = PlatformConfig( optdict, platname, cplrname )

    set_platform_options( platcfg, platopts )

    initialize_platform( platcfg )

    plat = Platform( mode=mode,
                     platname=platname,
                     cplrname=cplrname,
                     environ=platcfg.envD,
                     attrs=platcfg.attrs )

    plat.initialize( numprocs, maxprocs, devices, max_devices )

    return plat


class PlatformConfig:
    """
    This class is used as an interface to the platform_plugin.py mechanism.
    It is only necessary for backward compatibility, and allows the
    configuration mechanism to be separated from the implementation (the
    Platform class).
    """

    def __init__(self, optdict, platname, cplrname):
        ""
        self.optdict = optdict
        self.platname = platname
        self.cplrname = cplrname

        self.envD = {}
        self.attrs = {}

    def getName(self):  return self.platname
    def getCompiler(self): return self.cplrname
    def getOptions(self): return self.optdict

    def setenv(self, name, value):
        ""
        if value == None:
            if name in self.envD:
                del self.envD[name]
        else:
            self.envD[name] = value

    def setattr(self, name, value):
        ""
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

    def setBatchSystem(self, batchsys, ppnarg, **kwargs ):
        ""
        ppn = kwargs.get( 'ppn', kwargs.get( 'processors_per_node', ppnarg ) )
        assert ppn and ppn > 0

        self.setattr( 'batchsys', batchsys )

        for n,v in kwargs.items():
            self.setattr( n, v )

        if 'ppn' not in self.attrs:
            self.setattr( 'ppn', ppn )


# def get_aliased_attr( attrs, attrname, aliasname, valtype=str ):
#     ""
#     if attrname in attrs:
#         if aliasname in attrs:
#             a1 = valtype( attrs[attrname] )
#             a2 = valtype( attrs[aliasname] )
#             if a1 != a2:
#                 raise Exception( 'Platform attribute name and its alias were '
#                     'both given values, but they differ: ' + \
#                     attrname+'='+repr(attrs[attrname]) + ' != ' +\
#                     aliasname+'='+repr(attrs[aliasname]) )
#             attrs.pop( aliasname )
#         attrs[attrname] = valtype( attrs[attrname] )
#     elif aliasname in attrs:
#         attrs[attrname] = valtype( attrs[aliasname] )
#         attrs.pop( aliasname )

#     return attrs.get( attrname, None )


def set_platform_options( platcfg, platopts ):
    ""
    q = platopts.get( 'queue', platopts.get( 'q', None ) )
    platcfg.setattr( 'queue', q )

    act = platopts.get( 'account', platopts.get( 'PT', None ) )
    platcfg.setattr( 'account', act )

    wall = platopts.get( 'walltime', None )
    platcfg.setattr( 'walltime', wall )

    # QoS = "Quality of Service" e.g. "normal", "long", etc.
    QoS = platopts.get( 'QoS', None )
    platcfg.setattr( 'QoS', QoS )

    ppn = platopts.get( 'ppn', platopts.get( 'processors_per_node', None ) )
    if ppn is not None:
        ppn = int( ppn )
        assert ppn > 0
        platcfg.setattr( 'ppn', ppn )

    dpn = platopts.get( 'dpn', platopts.get( 'devices_per_node', None ) )
    if dpn is not None:
        dpn = int( dpn )
        assert dpn > 0
        platcfg.setattr( 'dpn', dpn )


def determine_platform_and_compiler( platname, onopts, offopts ):
    ""
    idplatform = import_idplatform()

    optdict = { '-o':onopts, '-O':offopts }
    if platname: optdict['--plat'] = platname

    if not platname:
        if idplatform is not None and hasattr( idplatform, "platform" ):
            platname = idplatform.platform( optdict )
        if not platname:
            platname = platform.uname()[0]

    cplrname = None
    if idplatform is not None and hasattr( idplatform, "compiler" ):
        cplrname = idplatform.compiler( platname, optdict )

    return platname, cplrname


def initialize_platform( platcfg ):
    ""
    plug = import_platform_plugin()

    if plug is not None and hasattr( plug, 'initialize' ):
        plug.initialize( platcfg )


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
