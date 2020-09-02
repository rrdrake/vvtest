
import sys, os
import threading
import traceback
import time

try:
  from StringIO import StringIO
except Exception:
  from io import StringIO


class BackgroundRunner:

    def __init__(self, maxconcurrent=20):
        ""
        self.maxrunning = maxconcurrent

        self.objs = []
        self.running = []

    def runall(self, run_objects):
        """
        Runs the given objects in the background until all are done. Each
        object must have a dispatch() method and a complete(exc,val) method.
        """
        self.objs = run_objects
        self.running = []

        while not self.isDone():

            self.checkRun()
            
            if self.checkFinished() == 0:
                time.sleep( 0.5 )

    def isDone(self):
        ""
        return len( self.objs ) == 0 and len( self.running ) == 0

    def checkRun(self):
        ""
        while len( self.running ) < self.maxrunning and len( self.objs ) > 0:
            obj = self.objs.pop()
            thr = ThreadedFunctionCall( obj.dispatch )
            self.running.append( [ thr, obj ] )

    def checkFinished(self):
        ""
        numfinished = 0

        runL = list( self.running )
        self.running = []

        for thr,obj in runL:
            if thr.isDone():
                exc,val = thr.getResult()
                obj.complete( exc, val )
                numfinished += 1
            else:
                self.running.append( [ thr,obj ] )

        return numfinished


class ThreadedFunctionCall( threading.Thread ):
    """
    Calls a function in a thread, such as

        thr = ThreadedFunctionCall( myfunc, myarg )
        while not thr.isDone():
            time.sleep(1)
        exc,value = thr.getResult()

    Where 'exc' is an exception traceback if one was caught, and 'value' is
    the return value of the run function.
    """

    def __init__(self, runfunc, *args, **kwargs):
        ""
        threading.Thread.__init__(self)
        self.daemon = True

        self.signature = ( runfunc, args, kwargs )

        self.lck = threading.Lock()
        self.result = None  # (exc,val) when done

        self.start()

    def run(self):
        ""
        try:
            exc = None
            val = None

            try:
                func,args,kwargs = self.signature
                val = func( *args, **kwargs )
            except Exception:
                sio = StringIO()
                traceback.print_exc( file=sio )
                exc = sio.getvalue()

            with self.lck:
                self.result = ( exc, val )

        except Exception as e:
            self.result = ( 'ThreadedFunctionCall error: '+str(e), None )

    def isDone(self):
        ""
        with self.lck:
            isdone = ( self.result != None )
        return isdone

    def getResult(self):
        """
        Returns (exc,value) if the thread is done. It is an error if not done.
        """
        with self.lck:
            res = self.result
        assert res != None, "thread is not done"
        return res
