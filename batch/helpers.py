#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import shlex
import subprocess


def compute_num_nodes( size, cores_per_node, devices_per_node ):
    ""
    np,ndevice = size

    nnode1 = compute_node_count( np, cores_per_node )

    if devices_per_node and ndevice:
        nnode2 = compute_node_count( ndevice, devices_per_node )
    else:
        nnode2 = 0

    return max( nnode1, nnode2 )


def compute_node_count( num, numper ):
    ""
    num = max( 0, num )
    if num > 0:
        nnode = int( num/numper )
        if (num%numper) != 0:
            nnode += 1
    else:
        nnode = 0

    return nnode


def runcmd( cmdL, changedir=None ):
    ""
    sys.stdout.flush()
    sys.stderr.flush()

    if changedir:
        cwd = os.getcwd()
        os.chdir( changedir )

    try:
        sp = subprocess.Popen( cmdL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT )
        out,err = sp.communicate()
    finally:
        if changedir:
            os.chdir( cwd )

    if sys.version_info[0] < 3:
        out = out if out else ''
    else:
        out = out.decode() if out else ''

    return sp.returncode, out


def format_extra_flags( extra_flags ):
    ""
    flags = []

    if extra_flags:
        if type(extra_flags) == type(''):
            flags = shlex.split(extra_flags)

        elif type(extra_flags) not in [type(()),type([])]:
            extra_flags_type = type(extra_flags).__name__
            errmsg = "Expected extra_flags to be str or list, not {0}"
            raise ValueError(errmsg.format(extra_flags_type))

        else:
            flags = list( extra_flags )

    return flags
