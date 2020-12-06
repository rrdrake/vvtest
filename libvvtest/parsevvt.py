#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

import os, sys
import re

from .errors import TestSpecError
from . import FilterExpressions
from . import timehandler

from .ScriptReader import check_parse_attributes_section

from .parseutil import variable_expansion
from .parseutil import evauate_testname_expr
from .parseutil import allowable_variable, allowable_string
from .parseutil import check_for_duplicate_parameter
from .parseutil import create_dependency_result_expression
from .parseutil import check_forced_group_parameter


def parse_vvt_test( inst ):
    ""
    parse_enable        ( inst )
    parse_keywords      ( inst )
    parse_working_files ( inst )
    parse_timeouts      ( inst )
    parse_baseline      ( inst )
    parse_dependencies  ( inst )
    parse_preload_label ( inst )

    inst.tfile.setSpecificationForm( 'script' )


def parse_test_names( vspecs ):
    """
    Determine the test name and check for validity.
    Returns a list of test names.
    """
    L = []

    specL = vspecs.getSpecList("testname") + vspecs.getSpecList("name")
    for spec in specL:

        if spec.attrs:
            raise TestSpecError( 'no attributes allowed here, ' + \
                                 'line ' + str(spec.lineno) )

        name,attrD = parse_test_name_value( spec.value, spec.lineno )

        if not name or not allowable_string(name):
            raise TestSpecError( 'missing or invalid test name, ' + \
                                 'line ' + str(spec.lineno) )
        L.append( name )

    if len(L) == 0:
        # the name defaults to the basename of the script file
        L.append( vspecs.basename() )

    return L


def parse_test_name_value( value, lineno ):
    ""
    name = value
    aD = {}

    sL = value.split( None, 1 )
    if len(sL) == 2:
        name,tail = sL

        if tail[0] == '#':
            pass

        elif tail[0] == '(':
            aD,tail = check_parse_attributes_section( tail, str(lineno) )
            check_test_name_attributes( aD, lineno )

        else:
            raise TestSpecError( 'invalid test name: ' + \
                    ', line ' + str(lineno) )

    return name, aD


def check_test_name_attributes( attrD, lineno ):
    ""
    if attrD:

        checkD = {}
        checkD.update( attrD )

        checkD.pop( 'depends on', None )
        checkD.pop( 'result', None )
        checkD.pop( 'expect', None )

        if len( checkD ) > 0:
            raise TestSpecError( 'unexpected attributes: ' + \
                ' '.join( checkD.keys() ) + ', line ' + str(lineno) )


def parse_keywords( inst ):
    """
    Parse the test keywords for the test script file.
    
      keywords : key1 key2
      keywords (testname=mytest) : key3
    
    Also includes the test name and the parameterize names.
    TODO: what other implicit keywords ??
    """
    keys = []

    for spec in inst.source.getSpecList( 'keywords' ):

        if spec.attrs:
            # explicitly deny certain attributes for keyword definition
            for attrname in ['parameters','parameter',
                             'platform','platforms',
                             'option','options']:
                if attrname in spec.attrs:
                    raise TestSpecError( "the "+attrname + \
                                " attribute is not allowed here, " + \
                                "line " + str(spec.lineno) )

        if not testname_ok_scr( spec.attrs, inst.testname ):
            continue

        for key in spec.value.strip().split():
            if allowable_string(key):
                keys.append( key )
            else:
                raise TestSpecError( 'invalid keyword: "'+key+'", line ' + \
                                     str(spec.lineno) )

    inst.tfile.setKeywordList( keys )


class FilterParsingInstance:

    def __init__(self, testname='', evaluator=None ):
        ""
        self.testname = testname
        self.evaluator = evaluator


def parse_parameterize( pset, vspecs, tname, evaluator, force_params ):
    """
    Parses the parameter settings for a script test file.

        #VVT: parameterize : np=1 4
        #VVT: parameterize (testname=mytest_fast) : np=1 4
        #VVT: parameterize (platforms=Cray or redsky) : np=128
        #VVT: parameterize (options=not dbg) : np=32
        
        #VVT: parameterize : dt,dh = 0.1,0.2  0.01,0.02  0.001,0.002
        #VVT: parameterize : np,dt,dh = 1, 0.1  , 0.2
        #VVT::                          4, 0.01 , 0.02
        #VVT::                          8, 0.001, 0.002
    """
    tmap = {}

    for spec in vspecs.getSpecList( 'parameterize' ):

        lnum = spec.lineno

        if spec.attrs and \
           ( 'parameters' in spec.attrs or 'parameter' in spec.attrs ):
            raise TestSpecError( "parameters attribute not allowed here, " + \
                                 "line " + str(lnum) )

        inst = FilterParsingInstance( testname=tname, evaluator=evaluator )
        if not attr_filter( spec.attrs, inst, lnum ):
            continue

        L = spec.value.split( '=', 1 )
        if len(L) < 2:
            raise TestSpecError( "invalid parameterize specification, " + \
                                 "line " + str(lnum) )

        namestr,valuestr = L

        if not namestr.strip():
            raise TestSpecError( "no parameter name given, " + \
                                 "line " + str(lnum) )
        if not valuestr.strip():
            raise TestSpecError( "no parameter value(s) given, " + \
                                 "line " + str(lnum) )

        nameL = [ n.strip() for n in namestr.strip().split(',') ]

        check_parameter_names( nameL, lnum )

        if len(nameL) == 1:
            valL = parse_param_values( nameL[0], valuestr, force_params )
            check_parameter_values( valL, lnum )
            check_special_parameters( nameL[0], valL, lnum )
        else:
            valL = parse_param_group_values( nameL, valuestr, lnum )
            check_forced_group_parameter( force_params, nameL, lnum )

        if spec.attrs and 'autotype' in spec.attrs:
            auto_determine_param_types( nameL, valL, tmap )

        staged = check_for_staging( spec.attrs, pset, nameL, valL, lnum )

        check_for_duplicate_parameter( valL, lnum )

        if len(nameL) == 1:
            pset.addParameter( nameL[0], valL )
        else:
            pset.addParameterGroup( nameL, valL, staged )

    pset.setParameterTypeMap( tmap )


def auto_determine_param_types( nameL, valL, tmap ):
    ""
    if len( nameL ) == 1:
        typ = try_cast_to_int_or_float( valL )
        if typ != None:
            tmap[ nameL[0] ] = typ

    else:
        for i,name in enumerate(nameL):
            typ = try_cast_to_int_or_float( [ tup[i] for tup in valL ] )
            if typ != None:
                tmap[ name ] = typ


def try_cast_to_int_or_float( valuelist ):
    ""
    for typ in [int,float]:
        if values_cast_to_type( typ, valuelist ):
            return typ
    return None


def values_cast_to_type( typeobj, valuelist ):
    ""
    try:
        vL = [ typeobj(v) for v in valuelist ]
    except Exception:
        return False
    return True


def check_for_staging( spec_attrs, pset, nameL, valL, lineno ):
    """
    for staged parameterize, the names & values are augmented. for example,

        nameL = [ 'pname' ] would become [ 'stage', 'pname' ]
        valL = [ 'val1', 'val2' ] would become [ ['1','val1'], ['2','val2'] ]
    """
    if spec_attrs and 'staged' in spec_attrs:

        if pset.getStagedGroup() != None:
            raise TestSpecError( 'only one parameterize can be staged' + \
                                 ', line ' + str(lineno) )

        insert_staging_into_names_and_values( nameL, valL )

        return True

    return False


def insert_staging_into_names_and_values( names, values ):
    ""
    if len( names ) == 1:
        values[:] = [ [str(i),v] for i,v in enumerate(values, start=1) ]
    else:
        values[:] = [ [str(i)]+vL for i,vL in enumerate(values, start=1) ]

    names[:] = [ 'stage' ] + names


def check_parameter_names( name_list, lineno ):
    ""
    for v in name_list:
        if not allowable_variable(v):
            raise TestSpecError( 'invalid parameter name: "' + \
                                 v+'", line ' + str(lineno) )


def check_parameter_values( value_list, lineno ):
    ""
    for v in value_list:
        if not allowable_string(v):
            raise TestSpecError( 'invalid parameter value: "' + \
                                 v+'", line ' + str(lineno) )


def check_special_parameters( param_name, value_list, lineno ):
    ""
    if param_name in [ 'np', 'ndevice' ]:
        for val in value_list:
            try:
                ival = int(val)
            except Exception:
                ival = None

            if ival == None or ival < 0:
                raise TestSpecError( 'np and ndevice parameter values '
                                     'must be non-negative integers: "' + \
                                     val+'", line ' + str(lineno) )


def parse_param_values( param_name, value_string, force_params ):
    ""
    if force_params != None and param_name in force_params:
        vals = force_params[ param_name ]
    else:
        vals = value_string.strip().split()

    return vals


spaced_comma_pattern = re.compile( '[\t ]*,[\t ]*' )

def parse_param_group_values( name_list, value_string, lineno ):
    ""
    compressed_string = spaced_comma_pattern.sub( ',', value_string.strip() )

    vL = []
    for s in compressed_string.split():

        gL = s.split(',')
        if len(gL) != len(name_list):
            raise TestSpecError( 'malformed parameter list: "' + \
                                  s+'", line ' + str(lineno) )

        check_parameter_values( gL, lineno )
        for name,val in zip( name_list, gL ):
            check_special_parameters( name, [val], lineno )

        vL.append( gL )

    return vL


def parse_analyze( tname, vspecs, evaluator ):
    """
    Parse any analyze specifications.
    
        #VVT: analyze : analyze.py
        #VVT: analyze : --analyze
        #VVT: analyze (testname=not mytest_fast) : --analyze

        - if the value starts with a hyphen, then an option is assumed
        - otherwise, a script file is assumed

    Returns true if an analyze specification was found.
    """
    form = None
    specval = None
    for spec in vspecs.getSpecList( 'analyze' ):

        if spec.attrs and \
           ( 'parameters' in spec.attrs or 'parameter' in spec.attrs ):
            raise TestSpecError( "parameters attribute not allowed here, " + \
                                 "line " + str(spec.lineno) )

        inst = FilterParsingInstance( testname=tname, evaluator=evaluator )
        if not attr_filter( spec.attrs, inst, spec.lineno ):
            continue

        if spec.attrs and 'file' in spec.attrs:
            raise TestSpecError( 'the "file" analyze attribute is ' + \
                                 'no longer supported, ' + \
                                 'line ' + str(spec.lineno) )

        if spec.attrs and 'argument' in spec.attrs:
            raise TestSpecError( 'the "argument" analyze attribute is ' + \
                                 'no longer supported, ' + \
                                 'line ' + str(spec.lineno) )

        sval = spec.value
        if not sval or not sval.strip():
            raise TestSpecError( 'missing or invalid analyze value, ' + \
                                 'line ' + str(spec.lineno) )

        specval = sval.strip()

    return specval


def parse_working_files( inst ):
    """
        #VVT: copy : file1 file2
        #VVT: link : file3 file4
        #VVT: copy (filters) : srcname1,copyname1 srcname2,copyname2
        #VVT: link (filters) : srcname1,linkname1 srcname2,linkname2

        #VVT: sources : file1 file2 ${NAME}_*.py
    """
    cpfiles = []
    lnfiles = []

    for spec in inst.source.getSpecList( 'copy' ):
        if attr_filter( spec.attrs, inst, spec.lineno ):
            collect_filenames( spec, cpfiles, inst.testname, inst.params,
                               inst.evaluator )

    for spec in inst.source.getSpecList( 'link' ):
        if attr_filter( spec.attrs, inst, spec.lineno ):
            collect_filenames( spec, lnfiles, inst.testname, inst.params,
                               inst.evaluator )
    
    for src,dst in lnfiles:
        inst.tfile.addLinkFile( src, dst )
    for src,dst in cpfiles:
        inst.tfile.addCopyFile( src, dst )

    fL = []
    for spec in inst.source.getSpecList( 'sources' ):
        if attr_filter( spec.attrs, inst, spec.lineno ):
            if spec.value:
                L = spec.value.split()
                variable_expansion( inst.testname,
                                    inst.evaluator.getPlatformName(),
                                    inst.params,
                                    L )
                fL.extend( L )
    inst.tfile.setSourceFiles( fL )


def collect_filenames( spec, flist, tname, paramD, evaluator ):
    """
        #VVT: copy : file1 file2
        #VVT: copy (rename) : srcname1,copyname1 srcname2,copyname2
    """
    val = spec.value.strip()

    if spec.attrs and 'rename' in spec.attrs:
        cpat = re.compile( '[\t ]*,[\t ]*' )
        fL = []
        for s in cpat.sub( ',', val ).split():
            L = s.split(',')
            if len(L) != 2:
                raise TestSpecError( 'malformed (rename) file list: "' + \
                                      s+'", line ' + str(spec.lineno) )
            fsrc,fdst = L
            if os.path.isabs(fsrc) or os.path.isabs(fdst):
                raise TestSpecError( 'file names cannot be absolute ' + \
                                     'paths, line ' + str(spec.lineno) )
            fL.append( [fsrc,fdst] )
        
        variable_expansion( tname, evaluator.getPlatformName(), paramD, fL )

        flist.extend( fL )

    else:
        fL = val.split()
        
        for f in fL:
            if os.path.isabs(f):
                raise TestSpecError( 'file names cannot be absolute ' + \
                                     'paths, line ' + str(spec.lineno) )
        
        variable_expansion( tname, evaluator.getPlatformName(), paramD, fL )

        flist.extend( [ [f,None] for f in fL ] )


def parse_timeouts( inst ):
    """
      #VVT: timeout : 3600
      #VVT: timeout : 2h 30m 5s
      #VVT: timeout : 2:30:05
      #VVT: timeout (testname=vvfull, platforms=Linux) : 3600
    """
    for spec in inst.source.getSpecList( 'timeout' ):
        if attr_filter( spec.attrs, inst, spec.lineno ):
            sval = spec.value

            ival,err = timehandler.parse_timeout_value( sval )

            if err:
                raise TestSpecError( 'invalid timeout value: '+err )

            inst.tfile.setTimeout( ival )


def parse_baseline( inst ):
    """
      #VVT: baseline : copyfrom,copyto copyfrom,copyto
      #VVT: baseline : --option-name
      #VVT: baseline : baseline.py
    
    where the existence of a comma triggers the first form
    otherwise, if the value starts with a hyphen then the second form
    otherwise, the value is the name of a filename
    """
    cpat = re.compile( '[\t ]*,[\t ]*' )

    for spec in inst.source.getSpecList( 'baseline' ):
        
        if attr_filter( spec.attrs, inst, spec.lineno ):
            
            sval = spec.value.strip()

            if not sval or not sval.strip():
                raise TestSpecError( 'missing or invalid baseline value, ' + \
                                     'line ' + str(spec.lineno) )

            if spec.attrs and 'file' in spec.attrs:
                raise TestSpecError( 'the "file" baseline attribute is ' + \
                                     'no longer supported, ' + \
                                     'line ' + str(spec.lineno) )

            if spec.attrs and 'argument' in spec.attrs:
                raise TestSpecError( 'the "argument" baseline attribute is ' + \
                                     'no longer supported, ' + \
                                     'line ' + str(spec.lineno) )

            if ',' in sval:
                form = 'copy'
            elif sval.startswith( '-' ):
                form = 'arg'
            else:
                form = 'file'

            if ',' in sval:
                fL = []
                for s in cpat.sub( ',', sval ).split():
                    L = s.split(',')
                    if len(L) != 2:
                        raise TestSpecError( 'malformed baseline file ' + \
                                  'list: "'+s+'", line ' + str(spec.lineno) )
                    fsrc,fdst = L
                    if os.path.isabs(fsrc) or os.path.isabs(fdst):
                        raise TestSpecError( 'file names cannot be ' + \
                                  'absolute paths, line ' + str(spec.lineno) )
                    fL.append( [fsrc,fdst] )
                
                variable_expansion( inst.testname,
                                    inst.evaluator.getPlatformName(),
                                    inst.params,
                                    fL )

                for fsrc,fdst in fL:
                    inst.tfile.addBaselineFile( fsrc, fdst )

            else:
                inst.tfile.setBaselineScript( sval )
                if not sval.startswith( '-' ):
                    inst.tfile.addLinkFile( sval )


def parse_dependencies( inst ):
    """
    Parse the test names that must run before this test can run.

        #VVT: depends on : test1 test2
        #VVT: depends on : test_pattern
        #VVT: depends on (result=pass) : testname
        #VVT: depends on (result="pass or diff") : testname
        #VVT: depends on (result="*") : testname

        #VVT: testname = testA (depends on=testB, result="*")
    """
    for spec in inst.source.getSpecList( 'depends on' ):
        if attr_filter( spec.attrs, inst, spec.lineno ):

            wx = create_dependency_result_expression( spec.attrs )
            exp = parse_expect_criterion( spec.attrs, spec.lineno )

            for val in spec.value.strip().split():
                inst.tfile.addDependency( val, wx, exp )

    specL = inst.source.getSpecList("testname") + inst.source.getSpecList("name")
    for spec in specL:

        name,attrD = parse_test_name_value( spec.value, spec.lineno )
        if name == inst.testname:

            wx = create_dependency_result_expression( attrD )
            exp = parse_expect_criterion( attrD, spec.lineno )

            for depname in attrD.get( 'depends on', '' ).split():
                inst.tfile.addDependency( depname, wx, exp )


def parse_expect_criterion( attrs, lineno ):
    ""
    exp = '+'

    if attrs:
        exp = attrs.get( 'expect', '+' ).strip("'")

    if exp not in ['+','*','?']:
        try:
            ival = int( exp )
            ok = True
        except Exception:
            ok = False

        if not ok or ival < 0:
            raise TestSpecError( "invalid 'expect' value, \""+str(exp) + \
                                 "\", line " + str(lineno) )

    return exp


def parse_preload_label( inst ):
    """
    #VVT: preload (filters) : label
    """
    for spec in inst.source.getSpecList( 'preload' ):
        if attr_filter( spec.attrs, inst, spec.lineno ):
            val = ' '.join( spec.value.strip().split() )
            inst.tfile.setPreloadLabel( val )


def testname_ok_scr( attrs, tname ):
    """
    """
    if attrs != None:
        tval = attrs.get( 'testname', None )
        if tval != None and not evauate_testname_expr( tname, tval ):
            return False
    return True


def attr_filter( attrs, inst, lineno ):
    """
    Checks for known attribute names in the given 'attrs' dictionary.
    Returns False only if at least one attribute evaluates to false.
    """
    if attrs:

        for name,value in attrs.items():

            try:

                if name == "testname":
                    if not evauate_testname_expr( inst.testname, value ):
                        return False

                elif name in ["platform","platforms"]:
                    if not inst.evaluator.evaluate_platform_expr( value ):
                        return False

                elif name in ["option","options"]:
                    wx = FilterExpressions.WordExpression( value )
                    if not inst.evaluator.evaluate_option_expr( wx ):
                        return False

                elif name in ["parameter","parameters"]:
                    pf = FilterExpressions.ParamFilter( value )
                    if not pf.evaluate( inst.params ):
                        return False

            except ValueError:
                raise TestSpecError( 'invalid '+name+' expression, ' + \
                                     'line ' + lineno + ": " + \
                                     str(sys.exc_info()[1]) )

    return True


def parse_enable( inst ):
    """
    Parse syntax that will filter out this test by platform or build option.
    
    Platform expressions and build options use word expressions.
    
        #VVT: enable (platforms="not SunOS and not Linux")
        #VVT: enable (options="not dbg and ( tridev or tri8 )")
        #VVT: enable (platforms="...", options="...")
        #VVT: enable = True
        #VVT: enable = False

    If both platform and option expressions are given, their results are
    ANDed together.  If more than one "enable" block is given, each must
    result in True for the test to be included.
    """
    for spec in inst.source.getSpecList( 'enable' ):

        platexpr = None
        opexpr = None

        if spec.attrs:

            if not testname_ok_scr( spec.attrs, inst.testname ):
                # the "enable" does not apply to this test name
                continue

            if 'parameters' in spec.attrs or 'parameter' in spec.attrs:
                raise TestSpecError( "parameters attribute not " + \
                                     "allowed here, line " + str(spec.lineno) )

            platexpr = spec.attrs.get( 'platforms',
                                       spec.attrs.get( 'platform', None ) )
            if platexpr != None:
                platexpr = platexpr.strip()
                if '/' in platexpr:
                    raise TestSpecError( \
                            'invalid "platforms" attribute value '
                            ', line ' + str(spec.lineno) )
                wx = FilterExpressions.WordExpression( platexpr )
                inst.tfile.addEnablePlatformExpression( wx )

            opexpr = spec.attrs.get( 'options',
                                     spec.attrs.get( 'option', None ) )
            if opexpr != None:
                opexpr = opexpr.strip()

                # an empty option expression is ignored
                if opexpr:
                    wx = FilterExpressions.WordExpression( opexpr )
                    inst.tfile.addEnableOptionExpression( wx )

        if spec.value:
            val = spec.value.lower().strip()
            if val != 'true' and val != 'false':
                raise TestSpecError( 'invalid "enable" value, line ' + \
                                     str(spec.lineno) )
            if val == 'false' and ( platexpr != None or opexpr != None ):
                raise TestSpecError( 'an "enable" with platforms or ' + \
                    'options attributes cannot specify "false", line ' + \
                    str(spec.lineno) )
            inst.tfile.setEnabled( val == 'true' )
