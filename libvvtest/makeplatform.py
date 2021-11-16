#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os
import platform

from .vvplatform import Platform


def create_Platform_instance( vvtestdir, platname, isbatched, platopts,
                              numprocs, maxprocs, devices, max_devices,
                              onopts, offopts ):
    ""
    assert vvtestdir
    assert os.path.exists( vvtestdir )
    assert os.path.isdir( vvtestdir )

    optdict = {}
    if platname:         optdict['--plat']    = platname
    if platopts:         optdict['--platopt'] = platopts
    if onopts:           optdict['-o']        = onopts
    if offopts:          optdict['-O']        = offopts

    plat = Platform( vvtestdir, optdict )

    platname,cplrname = get_platform_and_compiler(
                                platname,
                                None,  # compiler name not used anymore
                                onopts,
                                offopts )

    plat.platname = platname
    plat.cplrname = cplrname

    set_platform_options( plat, platopts )

    if isbatched:
        # this may get overridden by platform_plugin.py
        plat.setBatchSystem( 'procbatch', 1 )

    initialize_platform( plat )

    plat.initProcs( numprocs, maxprocs, devices, max_devices )

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
