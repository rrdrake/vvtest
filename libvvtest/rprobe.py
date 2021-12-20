#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import re
import platform
import subprocess


def probe_num_processors( fail_value=4 ):
    """
    Tries to determine the number of processors on the current machine.
    Returns the 'fail_value' if the probes fail.
    """
    mx = None

    if platform.uname()[0].startswith( 'Darwin' ):
        mx = num_cores_from_osx_sysctl()
        if mx is None:
            mx = num_cores_from_lscpu()

    else:
        mx = num_cores_from_lscpu()
        if mx is None:
            mx = num_cores_from_proc_cpuinfo()

    if not mx or mx < 1:
        mx = fail_value

    return mx


def num_cores_from_lscpu( fakedata=None ):
    ""
    nc = None

    try:
        data = fakedata if fakedata is not None else shell( 'lscpu' )
        for line in data.splitlines():
            if line.startswith( 'Core(s) per socket:' ):
                cores = int( line.split(':')[1] )
            elif line.startswith( 'Socket(s):' ):
                socks = int( line.split(':')[1] )
        nc = cores*socks
    except Exception:
        pass

    return nc


def num_cores_from_proc_cpuinfo( fakefile=None ):
    """
    count the number of lines of this pattern:

        processor       : <integer>
    """
    nc = None

    proc = re.compile( 'processor\s*:' )
    sibs = re.compile( 'siblings\s*:' )
    cores = re.compile( 'cpu cores\s*:' )
    try:
        fn = fakefile or '/proc/cpuinfo'
        with open( fn, 'rt' ) as fp:
            num_sibs = 0
            num_cores = 0
            cnt = 0
            for line in fp:
                if proc.match(line) is not None:
                    cnt += 1
                elif sibs.match(line) is not None:
                    num_sibs = int( line.split(':')[1] )
                elif cores.match(line) is not None:
                    num_cores = int( line.split(':')[1] )
            if cnt > 0:
                if num_sibs and num_cores and num_sibs > num_cores:
                    # eg, if num siblings is twice num cores, then physical
                    # cores is half the total processor count
                    fact = int( num_sibs//num_cores )
                    if fact > 0:
                        nc = cnt//fact
                    else:
                        nc = cnt
                else:
                    nc = cnt
    except Exception:
        pass

    return nc


def num_cores_from_osx_sysctl( fakedata=None ):
    ""
    try:
        if fakedata is None:
            data = shell( 'sysctl -n hw.physicalcpu' )
        else:
            data = fakedata
        nc = int( data.strip() )
    except Exception:
        nc = None

    return nc


def shell( cmd ):
    ""
    pop = subprocess.Popen( cmd, shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE )

    out,err = pop.communicate()

    if sys.version_info[0] < 3:
        out = out or ''
    else:
        out = out.decode() if out else ''

    return out
