#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import sys
sys.dont_write_bytecode = True
sys.excepthook = sys.__excepthook__
import os
import subprocess


def submit_file( cdash_url, project_name, filename, method='urllib' ):
    ""
    submit_url = cdash_url.rstrip('/')+'/submit.php'
    submit_url += '?project='+project_name

    assert method in ['urllib','curl']

    with set_environ( http_proxy='', HTTP_PROXY='',
                      https_proxy='', HTTPS_PROXY='' ):

        if method == 'urllib':
            submit_file_using_urllib( submit_url, filename )

        else:
            cmd = 'curl -T '+filename+' '+submit_url
            subprocess.check_call( cmd, shell=True )


def submit_file_using_urllib( submit_url, filename ):
    ""
    import urllib

    if hasattr( urllib, 'urlopen' ):
        content = read_file( filename, 'rt' )
        hnd = urllib.urlopen( submit_url, data=content, proxies={} )
        check_submit_response( hnd.getcode(), hnd.info() )
    else:
        # python 3
        from urllib.request import urlopen
        content = read_file( filename, 'rb' )
        hnd = urlopen( submit_url, data=content )
        check_submit_response( hnd.getcode(), hnd.info() )


def check_submit_response( code, msg ):
    ""
    if code not in [200,'200']:
        res = 'Unexpected response code: '+repr(code)
        for val in msg.headers:
            res += '\n'+val.strip()
        raise Exception( res )


def read_file( filename, mode ):
    ""
    with open( filename, mode ) as fp:
        contents = fp.read()

    return contents


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
