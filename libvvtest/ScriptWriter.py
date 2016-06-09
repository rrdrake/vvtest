#!/usr/bin/env python

import os, sys


def writeScript( testobj, filename, lang, config, plat ):
    """
    TODO: add helper functions for evaluating testname, options, parameters, etc
    """
    tname = testobj.getName()

    troot = testobj.getRootpath()
    assert os.path.isabs( troot )
    trel = os.path.dirname( testobj.getFilepath() )
    srcdir = os.path.normpath( os.path.join( troot, trel ) )
    
    tdir = config.get('toolsdir')
    assert tdir
    vvtlib = os.path.join( tdir, 'libvvtest' )

    projdir = config.get('exepath')
    if not projdir: projdir = ''

    onopts = config.get('onopts')
    offopts = config.get('offopts')

    platname = plat.getName()
    cplrname = plat.getCompiler()

    w = LineWriter()

    if lang == 'py':

        w.add( 'import os, sys',
               'sys.path.insert( 0, "'+vvtlib+'" )' )
        
        cdir = config.get('configdir')
        if cdir and os.path.exists( cdir ):
            w.add( 'sys.path.insert( 0, "'+cdir+'" )' )

        w.add( '',
               'NAME = "'+tname+'"',
               'PLATFORM = "'+platname+'"',
               'COMPILER = "'+cplrname+'"',
               'VVTESTSRC = "'+tdir+'"',
               'PROJECT = "'+projdir+'"',
               'OPTIONS = '+repr( onopts ),
               'OPTIONS_OFF = '+repr( offopts ),
               'SRCDIR = "'+srcdir+'"' )

        w.add( '', '# platform settings' )
        for k,v in plat.getEnvironment().items():
            w.add( 'os.environ["'+k+'"] = "'+v+'"' )

        w.add( '', '# parameters defined by the test' )
        paramD = testobj.getParameters()
        w.add( 'PARAM_DICT = '+repr( paramD ) )
        for k,v in paramD.items():
            w.add( k+' = "'+v+'"' )
        
        if testobj.getParent() == None and testobj.hasAnalyze():
            w.add( '', '# parameters comprising the children' )
            D = testobj.getParameterSet()
            if len(D) > 0:
              # the parameter names and values of the children tests
              for n,L in D.items():
                assert type(n) == type(())
                if len(n) == 1:
                    L2 = [ T[0] for T in L ]
                    w.add( 'PARAM_'+n[0]+' = ' + repr(L2) )
                else:
                    n2 = '_'.join( n )
                    w.add( 'PARAM_'+n2+' = ' + repr(L) )
        
        w.add( '', 'from script_util import *' )

        w.add( """
            def platform_expr( expr ):
                '''
                Evaluates the given word expression against the current
                platform name.  For example, the expression could be
                "Linux or Darwin" and would be true if the current platform
                name is "Linux" or if it is "Darwin".
                '''
                wx = FilterExpressions.WordExpression( expr )
                return wx.evaluate( lambda wrd: wrd == PLATFORM )
            
            def parameter_expr( expr ):
                '''
                Evaluates the given parameter expression against the parameters
                defined for the current test.  For example, the expression
                could be "dt<0.01 and dh=0.1" where dt and dh are parameters
                defined in the test.
                '''
                pf = FilterExpressions.ParamFilter( expr )
                return pf.evaluate( PARAM_DICT )
            
            def option_expr( expr ):
                '''
                Evaluates the given option expression against the options
                given on the vvtest command line.  For example, the expression
                could be "not dbg and not intel", which would be false if
                "-o dbg" or "-o intel" were given on the command line.
                '''
                wx = FilterExpressions.WordExpression( expr )
                return wx.evaluate( OPTIONS.count )
            """ )

        # TODO: import script_util_plugin.py from config directory
    
    elif lang in ['sh','bash']:

        w.add( '',
               'NAME="'+tname+'"',
               'PLATFORM="'+platname+'"',
               'COMPILER="'+cplrname+'"',
               'VVTESTSRC="'+tdir+'"',
               'PROJECT="'+projdir+'"',
               'OPTIONS="'+' '.join( onopts )+'"',
               'OPTIONS_OFF="'+' '.join( offopts )+'"',
               'SRCDIR="'+srcdir+'"' )

        w.add( '', '# platform settings' )
        for k,v in plat.getEnvironment().items():
            w.add( 'export '+k+'="'+v+'"' )

        w.add( '', '# parameters defined by the test' )
        paramD = testobj.getParameters()
        s = ' '.join( [ n+'/'+v for n,v in paramD.items() ] )
        w.add( 'PARAM_DICT="'+s+'"' )
        for k,v in paramD.items():
            w.add( k+'="'+v+'"' )
        
        if testobj.getParent() == None and testobj.hasAnalyze():
            w.add( '', '# parameters comprising the children' )
            D = testobj.getParameterSet()
            if len(D) > 0:
              # the parameter names and values of the children tests
              for n,L in D.items():
                assert type(n) == type(())
                n2 = '_'.join( n )
                L2 = [ '/'.join( v ) for v in L ]
                w.add( 'PARAM_'+n2+'="' + ' '.join(L2) + '"' )
        
        w.add( 'source '+ os.path.join( vvtlib, 'script_util.sh' ) )
        
        fex = sys.executable + ' ' + \
              os.path.join( vvtlib, 'FilterExpressions.py' )
        w.add( """
            platform_expr() {
                # Evaluates the given platform expression against the current
                # platform name.  For example, the expression could be
                # "Linux or Darwin" and would be true if the current platform
                # name is "Linux" or if it is "Darwin".
                # Returns 0 (zero) if the expression evaluates to true,
                # otherwise non-zero.
                
                result=`"""+fex+""" -f "$1" "$PLATFORM"`
                xval=$?
                if [ $xval -ne 0 ]
                then
                    echo "$result"
                    echo "*** error: failed to evaluate platform expression $1"
                    exit 1
                fi
                [ "$result" = "true" ] && return 0
                return 1
            }
            
            parameter_expr() {
                # Evaluates the given parameter expression against the
                # parameters defined for the current test.  For example, the
                # expression could be "dt<0.01 and dh=0.1" where dt and dh are
                # parameters defined in the test.
                # Returns 0 (zero) if the expression evaluates to true,
                # otherwise non-zero.
                
                result=`"""+fex+""" -p "$1" "$PARAM_DICT"`
                xval=$?
                if [ $xval -ne 0 ]
                then
                    echo "$result"
                    echo "*** error: failed to evaluate parameter expression $1"
                    exit 1
                fi
                [ "$result" = "true" ] && return 0
                return 1
            }
            
            option_expr() {
                # Evaluates the given option expression against the options
                # given on the vvtest command line.  For example, the expression
                # could be "not dbg and not intel", which would be false if
                # "-o dbg" or "-o intel" were given on the command line.
                # Returns 0 (zero) if the expression evaluates to true,
                # otherwise non-zero.
                
                result=`"""+fex+""" -o "$1" "$OPTIONS"`
                xval=$?
                if [ $xval -ne 0 ]
                then
                    echo "$result"
                    echo "*** error: failed to evaluate option expression $1"
                    exit 1
                fi
                [ "$result" = "true" ] && return 0
                return 1
            }
            """ )
    
    elif lang in ['csh','tcsh']:

        w.add( '',
               'set NAME="'+tname+'"',
               'set PLATFORM="'+platname+'"',
               'set COMPILER="'+cplrname+'"',
               'set VVTESTSRC="'+tdir+'"',
               'set PROJECT="'+projdir+'"',
               'set OPTIONS="'+' '.join( onopts )+'"',
               'set OPTIONS_OFF="'+' '.join( offopts )+'"',
               'set SRCDIR="'+srcdir+'"' )

        w.add( '', '# platform settings' )
        for k,v in plat.getEnvironment().items():
            w.add( 'setenv '+k+' "'+v+'"' )

        w.add( '', '# parameters defined by the test' )
        for k,v in testobj.getParameters().items():
            w.add( 'set '+k+'="'+v+'"' )
        
        if testobj.getParent() == None and testobj.hasAnalyze():
            w.add( '', '# parameters comprising the children' )
            D = testobj.getParameterSet()
            if len(D) > 0:
              # the parameter names and values of the children tests
              for n,L in D.items():
                assert type(n) == type(())
                n2 = '_'.join( n )
                L2 = [ '/'.join( v ) for v in L ]
                w.add( 'set PARAM_'+n2+'="' + ' '.join(L2) + '"' )
        
        w.add(  """
                set diff_exit_status=64
                set have_diff=0

                alias set_have_diff 'set have_diff=1'
                alias exit_diff 'echo "*** exitting diff" ; exit $diff_exit_status'
                alias if_diff_exit_diff 'if ( $have_diff ) echo "*** exitting diff" ; if ( $have_diff ) exit $diff_exit_status'
                """ )
    
    elif lang == 'pl':
        pass
    
    w.write( filename )


#########################################################################

class LineWriter:

    def __init__(self):
        self.lineL = []

    def add(self, *args):
        """
        """
        if len(args) > 0:
            indent = ''
            if type(args[0]) == type(2):
                n = args.pop(0)
                indent = '  '*n
            for line in args:
                if line.startswith('\n'):
                    for line in self._split( line ):
                        self.lineL.append( indent+line )
                else:
                    self.lineL.append( indent+line )

    def _split(self, s):
        """
        """
        off = None
        lineL = []
        for line in s.split( '\n' ):
            line = line.strip( '\r' )
            lineL.append( line )
            if off == None and line.strip():
                i = 0
                for c in line:
                    if c != ' ':
                        off = i
                        break
                    i += 1
        if off == None:
            return lineL
        return [ line[off:] for line in lineL ]

    def write(self, filename):
        """
        """
        fp = open( filename, 'w' )
        fp.write( '\n'.join( self.lineL ) + '\n' )
        fp.close()