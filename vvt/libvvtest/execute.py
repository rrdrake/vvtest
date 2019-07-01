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


def run_batch( batch, tlist, xlist, perms, results_writer,
               test_dir, qsublimit ):
    ""
    numjobs = batch.getNumNotRun()
    schedule = batch.getScheduler()

    print3( 'Total number of batch jobs: ' + str(batch.getNumNotRun()) + \
            ', maximum concurrent jobs: ' + str(qsublimit) )

    starttime = time.time()
    print3( "Start time:", time.ctime() )

    cwd = os.getcwd()
    qsleep = int( os.environ.get( 'VVTEST_BATCH_SLEEP_LENGTH', 15 ) )

    uthook = utesthooks.construct_unit_testing_hook( 'batch' )

    rfile = tlist.initializeResultsFile()
    for inclf in batch.getIncludeFiles():
        tlist.addIncludeFile( inclf )

    info = TestInformationPrinter( sys.stdout, tlist, batch )

    try:
        while True:

            qid = schedule.checkstart()
            if qid != None:
                # nothing to print here because the qsubmit prints
                pass
            elif schedule.numInFlight() == 0:
                break
            else:
                sleep_with_info_check( info, qsleep )

            qidL,doneL = schedule.checkdone()
            
            if len(qidL) > 0:
                ids = ' '.join( [ str(qid) for qid in qidL ] )
                print3( 'Finished batch IDS:', ids )
            for tcase in doneL:
                ts = XstatusString( tcase, test_dir, cwd )
                print3( "Finished:", ts )

            uthook.check( schedule.numInFlight(), schedule.numPastQueue() )

            if len(doneL) > 0:
                jpct = 100 * float(schedule.numDone()) / float(numjobs)
                jdiv = 'jobs '+str(schedule.numDone())+'/'+str(numjobs)
                jflt = '(in flight '+str(schedule.numStarted())+')'
                ndone = xlist.numDone()
                ntot = tlist.numActive()
                tpct = 100 * float(ndone) / float(ntot)
                tdiv = 'tests '+str(ndone)+'/'+str(ntot)
                dt = pretty_time( time.time() - starttime )
                print3( "Progress: " + \
                        jdiv+" = %%%.1f"%jpct + ' '+jflt+', ' + \
                        tdiv+" = %%%.1f"%tpct + ', ' + \
                        'time = '+dt )

        # any remaining tests cannot be run; flush then print warnings
        NS, NF, nrL = schedule.flush()

    finally:
        tlist.writeFinished()

    tlist.inlineIncludeFiles()

    perms.set( os.path.abspath( rfile ) )

    if len(NS)+len(NF)+len(nrL) > 0:
        print3()
    if len(NS) > 0:
      print3( "*** Warning: these batch numbers did not seem to start:",
              ' '.join(NS) )
    if len(NF) > 0:
      print3( "*** Warning: these batch numbers did not seem to finish:",
              ' '.join(NF) )
    for tcase0,tcase1 in nrL:
        assert tcase0.numDependencies() > 0 and tcase1 != None
        xdir = tcase1.getSpec().getExecuteDirectory()
        print3( '*** Warning: test "'+tcase0.getSpec().getExecuteDirectory()+'"',
                'notrun due to dependency "' + xdir + '"' )

    print3()
    results_writer.postrun( tlist )
    
    elapsed = pretty_time( time.time() - starttime )
    print3( "\nFinish date:", time.ctime() + " (elapsed time "+elapsed+")" )


def sleep_with_info_check( info, qsleep ):
    ""
    for i in range( int( qsleep + 0.5 ) ):
        info.checkPrint()
        time.sleep( 1 )


def run_test_list( qsub_id, tlist, xlist, test_dir, plat,
                   perms, results_writer ):
    ""
    plat.display()
    starttime = time.time()
    print3( "Start time:", time.ctime() )

    uthook = utesthooks.construct_unit_testing_hook( 'run', qsub_id )

    rfile = tlist.initializeResultsFile()

    try:

        info = TestInformationPrinter( sys.stdout, xlist )

        # execute tests

        perms.set( os.path.abspath( rfile ) )

        cwd = os.getcwd()

        while True:

            tnext = xlist.popNext( plat )

            if tnext != None:
                tspec = tnext.getSpec()
                texec = tnext.getExec()
                print3( 'Starting:', exec_path( tspec, test_dir ) )
                xlist.startTest( tnext, plat )
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

            if showprogress:
                ndone = xlist.numDone()
                ntot = tlist.numActive()
                pct = 100 * float(ndone) / float(ntot)
                div = str(ndone)+'/'+str(ntot)
                dt = pretty_time( time.time() - starttime )
                print3( "Progress: " + div+" = %%%.1f"%pct + ', time = '+dt )

    finally:
        tlist.writeFinished()

    # any remaining tests cannot run, so print warnings
    tcaseL = xlist.popRemaining()
    if len(tcaseL) > 0:
        print3()
    for tcase in tcaseL:
        deptx = tcase.getBlockingDependency()
        assert tcase.numDependencies() > 0 and deptx != None
        xdir = deptx.getSpec().getExecuteDirectory()
        print3( '*** Warning: test "'+tcase.getSpec().getExecuteDirectory()+'"',
                'notrun due to dependency "' + xdir + '"' )

    print3()
    results_writer.postrun( tlist )

    elapsed = pretty_time( time.time() - starttime )
    print3( "\nFinish date:", time.ctime() + " (elapsed time "+elapsed+")" )


def exec_path( testspec, test_dir ):
    ""
    xdir = testspec.getExecuteDirectory()
    return pathutil.relative_execute_directory( xdir, test_dir, os.getcwd() )


def print3( *args ):
    ""
    s = ' '.join( [ str(arg) for arg in args ] )
    sys.stdout.write( s + '\n' )
    sys.stdout.flush()