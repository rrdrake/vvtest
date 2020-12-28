#!/usr/bin/env python

# Copyright 2018 National Technology & Engineering Solutions of Sandia, LLC
# (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.

from .FilterExpressions import WordExpression
from .FilterExpressions import replace_forward_slashes
from .FilterExpressions import join_expressions_with_AND


class ParamFilter:

    def __init__(self, *expr):
        """
        If 'expr' is not None, load() is called.
        """
        self.wexpr = None
        self.wordD = {}
        if len( expr ) > 0:
            self.load(expr)

    def load(self, expr_list):
        """
        Loads the parameter specifications.  The 'expr' argument can be either
        a string word expression or a list of strings.

        If a list, each string is composed of parameter specifications
        separated by a '/' character.  A parameter specification is of the
        form:

            np        parameter np is defined
            np=       same as "np"
            !np       parameter np is not defined
            np!=      same as "!np"
            np<=4     parameter is less than or equal to four
            np>=4     parameter is greater than or equal to four
            np<4      parameter is less than four
            np>4      parameter is greater than four
            !np=4     not parameter is equal to four

        The parameter specifications separated by '/' are OR'ed together and
        the list entries are AND'ed together.

        Raises a ValueError if the expression contains a syntax error.
        """
        self.wexpr = WordExpression()
        for expr in expr_list:
            self.wexpr.append( expr )

        # map each word that appears to be an evaluation function object instance
        self.wordD = {}
        for w in self.wexpr.getWordList():
            self.wordD[w] = self._make_func(w)

    def evaluate(self, paramD):
        """
        Evaluate the expression previously loaded against the given parameter
        values.  Returns true or false.
        """
        if self.wexpr == None:
            return 1
        evalobj = ParamFilter.Evaluator(self.wordD, paramD)
        return self.wexpr._evaluate( evalobj.evaluate )

    class Evaluator:
        def __init__(self, wordD, paramD):
            self.wordD = wordD
            self.paramD = paramD
        def evaluate(self, word):
            return self.wordD[word].evaluate(self.paramD)

    def _make_func(self, word):
        """
        Returns an instance of an evaluation class based on the word.
        """
        if not word: raise ValueError( 'empty word (expected a word)' )
        if word[0] == '!':
            f = self._make_func( word[1:] )
            f.negate = not f.negate
            return f
        L = word.split( '<=', 1 )
        if len(L) > 1:
            if not L[1]: raise ValueError( "empty less-equal value" )
            return EvalLE( L[0], L[1] )
        L = word.split( '>=', 1 )
        if len(L) > 1:
            if not L[1]: raise ValueError( "empty greater-equal value" )
            return EvalGE( L[0], L[1] )
        L = word.split( '!=', 1 )
        if len(L) > 1:
            return EvalNE( L[0], L[1] )
        L = word.split( '<', 1 )
        if len(L) > 1:
            if not L[1]: raise ValueError( "empty less-than value" )
            return EvalLT( L[0], L[1] )
        L = word.split( '>', 1 )
        if len(L) > 1:
            if not L[1]: raise ValueError( "empty greater-than value" )
            return EvalGT( L[0], L[1] )
        L = word.split( '=', 1 )
        if len(L) > 1:
            return EvalEQ( L[0], L[1] )
        return EvalEQ( word, '' )


class EvalOperator:
    def __init__(self, param, value):
        if not param: raise ValueError( 'parameter name is empty' )
        self.p = param ; self.v = value
        self.negate = False
    def evaluate(self, paramD):
        b = self._eval_expr( paramD )
        if self.negate: b = not b
        return b


class EvalEQ( EvalOperator ):
    def _eval_expr(self, paramD):
        v = paramD.get(self.p,None)
        if self.v:
            if v == None: return 0  # paramD does not have the parameter
            if type(v) == type(2): return v == int(self.v)
            elif type(v) == type(2.2): return v == float(self.v)
            if v == self.v: return 1
            try:
                if int(v) == int(self.v): return 1
            except Exception: pass
            try:
                if float(v) == float(self.v): return 1
            except Exception: pass
            return 0
        return v != None  # true if paramD has the parameter name

class EvalNE( EvalOperator ):
    def _eval_expr(self, paramD):
        v = paramD.get(self.p,None)
        if self.v:
            if v == None: return 0  # paramD does not have the parameter
            if type(v) == type(2): return v != int(self.v)
            elif type(v) == type(2.2): return v != float(self.v)
            if v == self.v: return 0
            try:
                if int(v) == int(self.v): return 0
            except Exception: pass
            try:
                if float(v) == float(self.v): return 0
            except Exception: pass
            return 1
        return v == None  # true if paramD does not have the parameter name

class EvalLE( EvalOperator ):
    def _eval_expr(self, paramD):
        v = paramD.get(self.p,None)
        if v == None: return 0
        if type(v) == type(2): return v <= int(self.v)
        elif type(v) == type(2.2): return v <= float(self.v)
        if v == self.v: return 1
        try:
            if int(v) > int(self.v): return 0
            return 1
        except Exception: pass
        try:
            if float(v) > float(self.v): return 0
            return 1
        except Exception: pass
        return v <= self.v

class EvalGE( EvalOperator ):
    def _eval_expr(self, paramD):
        v = paramD.get(self.p,None)
        if v == None: return 0
        if type(v) == type(2): return v >= int(self.v)
        elif type(v) == type(2.2): return v >= float(self.v)
        if v == self.v: return 1
        try:
            if int(v) < int(self.v): return 0
            return 1
        except Exception: pass
        try:
            if float(v) < float(self.v): return 0
            return 1
        except Exception: pass
        return v >= self.v

class EvalLT( EvalOperator ):
    def _eval_expr(self, paramD):
        v = paramD.get(self.p,None)
        if v == None: return 0
        if type(v) == type(2): return v < int(self.v)
        elif type(v) == type(2.2): return v < float(self.v)
        if v == self.v: return 0
        try:
            if int(v) >= int(self.v): return 0
            return 1
        except Exception: pass
        try:
            if not float(v) < float(self.v): return 0
            return 1
        except Exception: pass
        return v < self.v

class EvalGT( EvalOperator ):
    def _eval_expr(self, paramD):
        v = paramD.get(self.p,None)
        if v == None: return 0
        if type(v) == type(2): return v > int(self.v)
        elif type(v) == type(2.2): return v > float(self.v)
        if v == self.v: return 0
        try:
            if int(v) <= int(self.v): return 0
            return 1
        except Exception: pass
        try:
            if not float(v) > float(self.v): return 0
            return 1
        except Exception: pass
        return v > self.v


def create_parameter_expression( param_expr_list, not_param_expr_list ):
    ""
    # construction will check validity

    exprL = []

    if param_expr_list:
        for expr in param_expr_list:
            ex = replace_forward_slashes( expr )
            ParamFilter( ex )
            exprL.append( ex )

    if not_param_expr_list:
        for expr in not_param_expr_list:
            ex = replace_forward_slashes( expr, negate=True )
            ParamFilter( ex )
            exprL.append( ex )

    if len( exprL ) > 0:
        return ParamFilter( join_expressions_with_AND( exprL ) )

    return None
