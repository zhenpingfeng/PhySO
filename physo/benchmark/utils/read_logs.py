import numpy as np
import pandas as pd
import sympy

# First column to contain free constants in Pareto front csv
START_COL_FREE_CONST_PARETO_CSV = 7
# todo: update for spe free consts
def read_pareto_csv (pareto_csv_path, sympy_X_symbols_dict = None, return_df = False):
    """
    Loads a Pareto front csv generated by PhySO into sympy expressions with evaluated free constants.
    Only works for expressions not using dataset spe free constants (ie. Class SR tasks), in those cases, pkl loading
    is recommended instead (physo.load_pareto_pkl).
    Parameters
    ----------
    pareto_csv_path : str
        Path to the Pareto front csv generated by PhySO.
    sympy_X_symbols_dict : dict of {str : sympy.Symbol} or None
        Input variables names to sympy symbols (w assumptions), can be passed to sympy.parsing.sympy_parser.parse_expr
        as local_dict.
    return_df : bool
        Whether to return the Pareto front dataframe too.
    Returns
    -------
    sympy_expressions : array_like of Sympy Expressions, or tuple of (array_like of Sympy Expressions, pd.DataFrame)
    """
    # Loading Pareto front csv
    pareto_df = pd.read_csv(pareto_csv_path)
    # Getting sympy expressions
    sympy_expressions = get_pareto_expressions_from_df(pareto_df=pareto_df, sympy_X_symbols_dict=sympy_X_symbols_dict)
    if return_df:
        return sympy_expressions, pareto_df
    else:
        return sympy_expressions

def get_pareto_expressions_from_df (pareto_df, sympy_X_symbols_dict = None):
    """
    Loads a Pareto front dataframe generated by PhySO into sympy expressions with evaluated free constants.
    Only works for expressions not using dataset spe free constants (ie. Class SR tasks).
    Parameters
    ----------
    pareto_df : pd.DataFrame
        Pareto front dataframe generated by PhySO.
    sympy_X_symbols_dict : dict of {str : sympy.Symbol} or None
        Input variables names to sympy symbols (w assumptions), can be passed to sympy.parsing.sympy_parser.parse_expr
        as local_dict.
    Returns
    -------
    sympy_expressions : array_like of Sympy Expressions
    """
    # Initializing list of sympy expressions
    sympy_expressions = []
    # Names of free constants
    free_consts_names = pareto_df.columns.to_numpy()[START_COL_FREE_CONST_PARETO_CSV:].astype(str)
    # Nb of free constants
    n_fconsts = len(free_consts_names)
    # Iterating through Pareto optima expressions
    for i_expr in range (len(pareto_df)):
        # Expression str
        expr_str = str(pareto_df["expression"].iloc[i_expr]) # Force str in case only a float is present as expression
        # Free const name to value dict, replacing nans by 1
        free_const_dict = {free_consts_names[i_const]: np.nan_to_num(
                                                    pareto_df[free_consts_names[i_const]].iloc[i_expr],
                                                    nan=1.)
                           for i_const in range(n_fconsts)}
        # Variables + const to their values or symbols dict
        local_dict = {}
        if sympy_X_symbols_dict is not None:
            local_dict.update(sympy_X_symbols_dict)
        local_dict.update(free_const_dict)
        # Sympy formula with free constants replaced by their values and variables symbols having assumptions
        formula_sympy = sympy.parsing.sympy_parser.parse_expr(expr_str,
                                                              local_dict = local_dict,
                                                              evaluate   = True,)
        sympy_expressions.append(formula_sympy)
    return sympy_expressions
