#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import time

from . import utesthooks
from . import pathutil
from .printinfo import TestInformationPrinter
from .outpututils import XstatusString, pretty_time


class TestListRunner:

    def __init__(self, test_dir, tlist, xlist, perms,
                       rtinfo, results_writer, plat):
        ""
        self.test_dir = test_dir
        self.tlist = tlist
        self.xlist = xlist
        self.perms = perms
        self.rtinfo = rtinfo
        self.results_writer = results_writer
        self.plat = plat

    def runDirect(self, qsub_id):
        ""
        run_test_list( qsub_id, self.tlist, self.xlist, self.test_dir, self.plat,
                       self.perms, self.rtinfo, self.results_writer )

    def runBatch(self, batch):
        ""
        self.plat.display( isbatched=True )

        self.tlist.setResultsDate()

        batch.writeQsubScripts()

        run_batch( batch, self.tlist, self.xlist, self.perms,
                   self.rtinfo, self.results_writer, self.test_dir )


def run_batch( batch, tlist, xlist, perms, rtinfo, results_writer, test_dir ):
    ""
    print3( 'Maximum concurrent batch jobs:', batch.getMaxJobs() )

    starttime = time.time()
    print3( "Start time:", time.ctime() )

    cwd = os.getcwd()
    qsleep = int( os.environ.get( 'VVTEST_BATCH_SLEEP_LENGTH', 15 ) )

    uthook = utesthooks.construct_unit_testing_hook( 'batch' )

    rfile = tlist.initializeResultsFile( **rtinfo.asDict() )
    perms.apply( os.path.abspath( rfile ) )

    info = TestInformationPrinter( sys.stdout, tlist, batch )

    try:
        while True:

            qid = batch.checkstart()
            if qid != None:
                # nothing to print here because the qsubmit prints
                pass
            elif batch.numInProgress() == 0:
                break
            else:
                sleep_with_info_check( info, qsleep )

            qidL,doneL = batch.checkdone()
            
            if len(qidL) > 0:
                ids = ' '.join( [ str(qid) for qid in qidL ] )
                print3( 'Finished batch IDS:', ids )
            for tcase in doneL:
                ts = XstatusString( tcase, test_dir, cwd )
                print3( "Finished:", ts )

            uthook.check( batch.numInProgress(), batch.numPastQueue() )

            results_writer.midrun( tlist, rtinfo )

            if len(doneL) > 0:
                sL = [ get_batch_info( batch ),
                       get_test_info( tlist, xlist ),
                       'time = '+pretty_time( time.time() - starttime ) ]
                print3( "Progress:", ', '.join( sL )  )

        # any remaining tests cannot be run, so flush them
        NS, NF, nrL = batch.flush()

    finally:
        batch.shutdown()

    if len(NS)+len(NF)+len(nrL) > 0:
        print3()
    if len(NS) > 0:
        print3( "*** Warning: these batch numbers did not seem to start:",
                ' '.join(NS) )
    if len(NF) > 0:
        print3( "*** Warning: these batch numbers did not seem to finish:",
                ' '.join(NF) )
    print_notrun_reasons( nrL )


def print_notrun_reasons( notrunlist ):
    ""
    for tcase,reason in notrunlist:
        xdir = tcase.getSpec().getDisplayString()
        print3( '*** Warning: test "'+xdir+'"',
                'notrun due to "' + reason + '"' )


def get_batch_info( batch ):
    ""
    ndone = batch.getNumDone()
    nrun = batch.numInProgress()

    return 'jobs running='+str(nrun)+' completed='+str(ndone)


def get_test_info( tlist, xlist ):
    ""
    ndone = xlist.numDone()
    ntot = tlist.numActive()
    tpct = 100 * float(ndone) / float(ntot)
    tdiv = 'tests '+str(ndone)+'/'+str(ntot)

    return tdiv+" = %%%.1f"%tpct


def sleep_with_info_check( info, qsleep ):
    ""
    for i in range( int( qsleep + 0.5 ) ):
        info.checkPrint()
        time.sleep( 1 )


def run_test_list( qsub_id, tlist, xlist, test_dir, plat,
                   perms, rtinfo, results_writer ):
    ""
    plat.display()
    starttime = time.time()
    print3( "Start time:", time.ctime() )

    uthook = utesthooks.construct_unit_testing_hook( 'run', qsub_id )

    rfile = tlist.initializeResultsFile( **rtinfo.asDict() )
    perms.apply( os.path.abspath( rfile ) )

    info = TestInformationPrinter( sys.stdout, xlist )

    try:

        # execute tests

        cwd = os.getcwd()

        while True:

            tnext = xlist.popNext( plat.sizeAvailable() )

            if tnext != None:
                tspec = tnext.getSpec()
                texec = tnext.getExec()
                print3( 'Starting:', exec_path( tspec, test_dir ) )
                start_test( xlist, tnext, plat )
                tlist.appendTestResult( tnext )

            elif xlist.numRunning() == 0:
                break

            else:
                info.checkPrint()
                time.sleep(1)

            showprogress = False
            for tcase in list( xlist.getRunning() ):
                tx = tcase.getExec()
                if tx.poll():
                    xs = XstatusString( tcase, test_dir, cwd )
                    print3( "Finished:", xs )
                    xlist.testDone( tcase )
                    showprogress = True

            uthook.check( xlist.numRunning(), xlist.numDone() )

            results_writer.midrun( tlist, rtinfo )

            if showprogress:
                ndone = xlist.numDone()
                ntot = tlist.numActive()
                pct = 100 * float(ndone) / float(ntot)
                div = str(ndone)+'/'+str(ntot)
                dt = pretty_time( time.time() - starttime )
                print3( "Progress: " + div+" = %%%.1f"%pct + ', time = '+dt )

        nrL = xlist.popRemaining()  # these tests cannot be run

    finally:
        tlist.writeFinished()

    if len(nrL) > 0:
        print3()
    print_notrun_reasons( nrL )


def exec_path( testspec, test_dir ):
    ""
    xdir = testspec.getDisplayString()
    return pathutil.relative_execute_directory( xdir, test_dir, os.getcwd() )


def run_baseline( xlist, plat ):
    ""
    failures = False

    for tcase in xlist.consumeBacklog():

        tspec = tcase.getSpec()
        texec = tcase.getExec()

        xdir = tspec.getDisplayString()

        sys.stdout.write( "baselining "+xdir+"..." )

        start_test( xlist, tcase, plat, is_baseline=True )

        tm = int( os.environ.get( 'VVTEST_BASELINE_TIMEOUT', 30 ) )
        for i in range(tm):

            time.sleep(1)

            if texec.poll():
                if tcase.getStat().passed():
                    print3( "done" )
                else:
                    failures = True
                    print3("FAILED")
                break

        if not tcase.getStat().isDone():
            texec.killJob()
            failures = True
            print3( "TIMED OUT" )

    if failures:
        print3( "\n\n !!!!!!!!!!!  THERE WERE FAILURES  !!!!!!!!!! \n\n" )


def start_test( xlist, tcase, platform, is_baseline=False ):
    ""
    obj = platform.getResources( tcase.getSize() )

    texec = tcase.getExec()
    texec.setResourceObject( obj )
    texec.start( is_baseline )

    tcase.getStat().markStarted( texec.getStartTime() )


def encode_integer_warning( tlist ):
    ""
    ival = 0

    for tcase in tlist.getTests():
        if not tcase.getStat().skipTest():
            result = tcase.getStat().getResultStatus()
            if   result == 'diff'   : ival |= ( 2**1 )
            elif result == 'fail'   : ival |= ( 2**2 )
            elif result == 'timeout': ival |= ( 2**3 )
            elif result == 'notdone': ival |= ( 2**4 )
            elif result == 'notrun' : ival |= ( 2**5 )

    return ival


def print3( *args ):
    ""
    sys.stdout.write( ' '.join( [ str(arg) for arg in args ] ) + '\n' )
    sys.stdout.flush()
