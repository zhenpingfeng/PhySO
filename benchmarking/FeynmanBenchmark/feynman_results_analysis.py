import warnings
import numpy as np
import sympy
import pandas as pd
import argparse
import scipy.stats as st
import os
import time

# Internal imports
import physo.benchmark.FeynmanDataset.FeynmanProblem as Feyn
# Local imports
import feynman_config as fconfig
from benchmarking.utils import timeout_unix
from benchmarking.utils import metrics_utils
from benchmarking.utils import utils

# ---------------------------------------------------- SCRIPT ARGS -----------------------------------------------------
parser = argparse.ArgumentParser (description     = "Analyzes Feynman run results folder (works on ongoing benchmarks) "
                                                    "and produces .csv files containing results and a summary.",
                                  formatter_class = argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument("-n", "--noise",
                    help = "Noise to encode in log results files.")
parser.add_argument("-p", "--path", default = ".",
                    help = "Paths to results folder.")
config = vars(parser.parse_args())

NOISE_LVL    = float(config["noise"])
RESULTS_PATH = str(config["path"])
# ---------------------------------------------------- SCRIPT ARGS -----------------------------------------------------

N_TRIALS = fconfig.N_TRIALS
EXCLUDED_IN_SRBENCH_EQS_FILENAMES = fconfig.EXCLUDED_IN_SRBENCH_EQS_FILENAMES

# Where to save raw results of all runs
PATH_RESULTS_SAVE         = os.path.join(RESULTS_PATH, "results_detailed.csv")
# Grouped by problem
PATH_RESULTS_SUMMARY_SAVE = os.path.join(RESULTS_PATH, "results_summary.csv")
# Grouped by problem and keeping only essential columns
PATH_RESULTS_ESSENTIAL_SAVE = os.path.join(RESULTS_PATH, "results_summary_essential.csv")
# Statistics on the results
PATH_RESULTS_STATS_SAVE = os.path.join(RESULTS_PATH, "results_stats.txt")
# Path where to save jobfile to relaunch unfinished jobs
PATH_UNFINISHED_JOBFILE = os.path.join(RESULTS_PATH, "jobfile_unfinished")

# First column to contain free constants in Pareto front csv
START_COL_FREE_CONST_PARETO_CSV = 6

# Only assessing symbolic equivalence if reward is above:
R_LIM = 0.6

def load_pareto_expressions (pareto_df, sympy_X_symbols_dict):
    """
    Loads a Pareto front dataframe generated by PhySO into sympy expressions with evaluated free constants.
    Parameters
    ----------
    pareto_df : pd.DataFrame
        Pareto front dataframe generated by PhySO.
    sympy_X_symbols_dict : dict of {str : sympy.Symbol}
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
        expr_str = pareto_df["expression"].iloc[i_expr]
        # Free const name to value dict, replacing nans by 1
        free_const_dict = {free_consts_names[i_const]: np.nan_to_num(
                                                    pareto_df[free_consts_names[i_const]].iloc[i_expr],
                                                    nan=1.)
                           for i_const in range(n_fconsts)}
        # Variables + const to their values or symbols dict
        local_dict = {}
        local_dict.update(sympy_X_symbols_dict)
        local_dict.update(free_const_dict)
        # Sympy formula with free constants replaced by their values and variables symbols having assumptions
        formula_sympy = sympy.parsing.sympy_parser.parse_expr(expr_str,
                                                              local_dict = local_dict,
                                                              evaluate   = True,)
        sympy_expressions.append(formula_sympy)
    return sympy_expressions


@timeout_unix.timeout(20) # Max 20s wrapper
def timed_compare_expr(Feynman_pb, trial_expr, verbose):
    return Feynman_pb.compare_expression(trial_expr=trial_expr, verbose=verbose)

def assess_equivalence (pareto_df, Feynman_pb, verbose = False):
    """
    Checks if at least one expression in the Pareto front is symbolically equivalent to target expression, following a
    similar methodology as SRBench (see https://github.com/cavalab/srbench).
    I.e, an expression is deemed equivalent if:
        - the symbolic difference simplifies to 0
        - OR the symbolic difference is a constant
        - OR the symbolic ratio simplifies to a constant
    Parameters
    ----------
    pareto_df : pd.DataFrame
        Pareto front dataframe generated by PhySO.
    Feynman_pb : physo.benchmark.FeynmanDataset.FeynmanProblem.FeynmanProblem
        Related Feynman problem.
    verbose : bool
        Verbose.
    Returns
    -------
    is_equivalent : bool
        Is at least one expression equivalent.
    """

    # Nb of expressions in Pareto front
    n_expr = len(pareto_df)
    # Loading rewards of Pareto fronts
    rewards = pareto_df["reward"].to_numpy()
    # Loading Pareto front expressions
    pareto_expressions = load_pareto_expressions(pareto_df            = pareto_df,
                                                 sympy_X_symbols_dict = Feynman_pb.sympy_X_symbols_dict, )

    equivalence_list = []
    report_list      = []
    # Iterating through Pareto front expressions (starting with most accurate/complex and going down)
    for i in reversed (range (n_expr)):
        r          = rewards            [i]
        trial_expr = pareto_expressions [i]

        # Verbose
        if verbose:
            print(" -> reward = %f -> analyzing " % (r))

        # Only assessing symbolic equivalence if reward is above threshold
        if r > R_LIM:

            # Equivalence check
            try:
                is_equivalent, report = timed_compare_expr(Feynman_pb  = Feynman_pb,
                                                           trial_expr  = trial_expr,
                                                           verbose     = verbose)
            except:
                # Negative report
                is_equivalent = False
                report = {
                    'symbolic_error'                : '',
                    'symbolic_fraction'             : '',
                    'symbolic_error_is_zero'        : None,
                    'symbolic_error_is_constant'    : None,
                    'symbolic_fraction_is_constant' : None,
                    'sympy_exception'               : "Timeout",
                    'symbolic_solution'             : False,
                }
                warnings.warn("Sympy timeout.")
            equivalence_list .append(is_equivalent)
            report_list      .append(report)

            # If equivalent no need to check further down Pareto front
            if is_equivalent:
                break

        else:
            print(" -> reward = %f < %f -> no need to analyze further"%(r, R_LIM))
            # Negative report
            is_equivalent = False
            report = {
                'symbolic_error'                : '',
                'symbolic_fraction'             : '',
                'symbolic_error_is_zero'        : None,
                'symbolic_error_is_constant'    : None,
                'symbolic_fraction_is_constant' : None,
                'sympy_exception'               : "LowReward",
                'symbolic_solution'             : False,
            }
            equivalence_list .append(is_equivalent)
            report_list      .append(report)

        # Verbose
        if verbose and r > 0.9900 and (is_equivalent is False):
            print("  -> Weird reward = %f and yet this expression was not deemed equivalent." % (r))

    equivalence_list = np.array(equivalence_list)
    report_list      = np.array(report_list)

    # If there is at least one equivalent expression
    if equivalence_list.any():
        # Idx of 1st instance (in reverse Pareto i.e. most accurate/complex) of equivalent expression
        i_equivalent = np.argwhere(equivalence_list == True)[0,0]
        if i_equivalent != 0:
            warnings.warn("Equivalent expression was not the most Pareto accurate one.")
        # Result
        res_equivalent = equivalence_list  [i_equivalent]
        res_report     = report_list       [i_equivalent]
    # No equivalent expression in Pareto front
    else:
        # Any negative report will do
        res_equivalent = equivalence_list  [0]
        res_report     = report_list       [0]

    return res_equivalent, res_report

def assess_metric_test (pareto_df, Feynman_pb, metric_func):
    """
    Computes metric value of the best Pareto front expression on noiseless test data.
    Parameters
    ----------
    pareto_df : pd.DataFrame
        Pareto front dataframe generated by PhySO.
    Feynman_pb : physo.benchmark.FeynmanDataset.FeynmanProblem.FeynmanProblem
        Related Feynman problem.
    metric_func : callable
        Function taking target (y_target) of shape (?,) and prediction (y_pred) of shape (?,) computing the metric.
    Returns
    -------
    metric_value : float
    """
    # Loading Pareto front expressions
    pareto_expressions = load_pareto_expressions(pareto_df            = pareto_df,
                                                 sympy_X_symbols_dict = Feynman_pb.sympy_X_symbols_dict, )
    # Generate test data
    X, y = pb.generate_data_points(fconfig.N_SAMPLES_TEST)
    y_target = y
    # Evaluate on trial expression
    trial_expr = pareto_expressions[-1]
    y_pred = pb.trial_function(trial_expr, X)
    # Compute metric
    metric_value = metric_func(y_target, y_pred)
    return metric_value

def load_run_data (pb_folder_prefix):
    """
    Safely loads pareto front .csv and curves data .csv into dataframes if possible return None otherwise.
    Also returns noise level encoded into folder name.
    Parameters
    ----------
    pb_folder_prefix : str or path
        Starting name of folder containing run data (there should only be one folder starting with this name).
    Returns
    -------
    pareto_data, curves_data, noise_lvl : (pd.DataFrame or None, pd.DataFrame or None, float incl. NaN)
    """
    # ----- Locating run data -----
    # Getting folder starting with [pb_folder_prefix] str
    # Working with prefix is better as the ending will depend on noise lvl applied during this benchmarking campaign
    pb_folder = list(filter(lambda folders: pb_folder_prefix in folders, os.listdir(RESULTS_PATH)))
    if len(pb_folder) != 0:
        pb_folder = pb_folder[0]
        print("-> Analyzing run folder: %s" % (pb_folder))
        path_pareto = os.path.join(RESULTS_PATH, pb_folder, 'SR_curves_pareto.csv')
        path_curves = os.path.join(RESULTS_PATH, pb_folder, 'SR_curves_data.csv')
        noise_lvl   = pb_folder.split("_")[-1]
    else:
        warnings.warn("Unable to find folder starting with: %s" % (pb_folder_prefix))
        path_pareto = None
        path_curves = None
        noise_lvl   = np.NAN

    # ----- Loading data -----
    try:
        # Loading pareto expressions
        pareto_data = pd.read_csv(path_pareto)
    except:
        warnings.warn("Unable to load Pareto .csv: %s" % (pb_folder_prefix))
        pareto_data = None
    try:
        # Loading curves data
        curves_data = pd.read_csv(path_curves)
    except:
        warnings.warn("Unable to load curves data .csv: %s" % (pb_folder_prefix))
        curves_data = None

    return pareto_data, curves_data, noise_lvl

t000 = time.time()
# ------- Results df -------
# Columns are from SRBench except for columns in upper cases which are added in the context of PhySO:
# 'EQ NB'         : eq nb in Feynman set (0 to 99 for bulk and 100 to 119 for bonuses)
# '# EVALUATIONS' : nb of evaluations
# 'STARTED'       : Was run successfully started
# 'FINISHED'      : Was run successfully finished (ie. not terminated early)

# Column name, dtype, [aggregation method across a single Feynman problem OR False if it should not be aggregated
# OR True if it is an aggregation key]
columns = [
    # Test settings
    ('algorithm'    , str   , True    ),
    ('data_group'   , str   , True    ),
    ('dataset'      , str   , True    ),
    ('EQ NB'        , int   , True    ),
    ('random_state' , int   , False   ),
    ('target_noise' , float , True    ),
    ('true_model'   , str   , True    ),
    # Run details
    ('# EVALUATIONS' , int  , np.sum),
    ('STARTED'       , bool , np.sum),
    ('FINISHED'      , bool , np.sum),
    # Symbolic results related
    ('symbolic_model'            , str   , False   ),
    ('model_size'                , float , np.mean ),
    ('simplified_symbolic_model' , str   , False   ),
    ('simplified_complexity'     , float , np.mean ),
    # Symbolic equivalence assessment
    ('symbolic_error'                , str  , False   ),
    ('symbolic_fraction'             , str  , False   ),
    ('symbolic_error_is_zero'        , bool , np.sum  ),
    ('symbolic_error_is_constant'    , bool , np.sum  ),
    ('symbolic_fraction_is_constant' , bool , np.sum  ),
    ('sympy_exception'               , str  , False   ),
    ('symbolic_solution'             , bool , np.mean ),
    # Numeric accuracy related (aggregated using a median as SRBench)
    ('mse_test'     , float, np.median ),
    ('mae_test'     , float, np.median ),
    ('r2_test'      , float, np.median ),
    ('r2_zero_test' , float, np.median ),
]
columns_names  = [x[0] for x in columns]
columns_dtypes = {x[0]:x[1] for x in columns}
columns_to_aggregate_on     = [x[0] for x in columns if x[2] is True]
columns_aggregation_methods = {x[0] : x[2] for x in columns if x[2] is not True and x[2] is not False}

# Initializing results df
results_df = pd.DataFrame(columns=columns_names).astype(columns_dtypes)
# List of all lines that will be converted to pd.DataFrame (as df.append is deprecated).
all_results = []

# Column info that will be the same for all rows
ALGORITHM  = "PhySO"
DATA_GROUP = "Feynman"

# Unfinished jobs list
unfinished_jobs = []

# Iterating through Feynman problems
for i_eq in range (Feyn.N_EQS):
    print("\nProblem #%i"%(i_eq))
    # Loading a problem
    pb = Feyn.FeynmanProblem(i_eq)
    # Considering the problem only if it is not excluded
    if pb.eq_filename not in EXCLUDED_IN_SRBENCH_EQS_FILENAMES:
        print(pb)
        # Iterating through trials
        for i_trial in range (N_TRIALS):
            run_result = {}

            # ----- Loading run data -----
            pareto_df, curves_df, noise_lvl = load_run_data(pb_folder_prefix = "FR_%s_%s"%(i_eq, i_trial))

            # If folder could not be found, take noise level from arg
            # if np.isnan(noise_lvl):
            # Always taking it from arg for consistency
            noise_lvl = NOISE_LVL

            # ----- Logging test settings -----
            run_settings = {
                'algorithm'    : ALGORITHM,
                'data_group'   : DATA_GROUP,
                'dataset'      : pb.SRBench_name,
                'EQ NB'        : pb.i_eq,
                'random_state' : i_trial,
                'target_noise' : noise_lvl,
                # Saving true_model with evaluated fixed const (eg. 1/sqrt(2pi) = 0.399) SRBench style
                'true_model'   : str(Feyn.clean_sympy_expr(pb.formula_sympy)),
            }
            run_result.update(run_settings)

            # ----- Logging run details -----
            try:
                n_evals     = curves_df["n_rewarded"].sum()
                is_started  = curves_df["epoch"].iloc[-1] >= 0
                is_finished = n_evals >= (fconfig.MAX_N_EVALUATIONS - fconfig.CONFIG["learning_config"]["batch_size"] - 1)
            except:
                # If curves were not loaded -> run was not started
                n_evals     = 0
                is_started  = False
                is_finished = False

            run_details = {
                '# EVALUATIONS' : n_evals,
                'STARTED'       : is_started,
                'FINISHED'      : is_finished,
                }
            run_result.update(run_details)

            # ----- Listing unfinished jobs -----

            if not is_finished :
                command = "python feynman_run.py -i %i -t %i -n %f"%(i_eq, i_trial, noise_lvl)
                unfinished_jobs.append(command)
                utils.make_jobfile_from_command_list(PATH_UNFINISHED_JOBFILE, unfinished_jobs)

            # ----- Symbolic results related -----

            try:
                pareto_expressions = load_pareto_expressions(pareto_df            = pareto_df,
                                                             sympy_X_symbols_dict = pb.sympy_X_symbols_dict, )

                best_expr = pareto_expressions[-1]
                symbolic_model = str(best_expr)
                model_size     = Feyn.complexity(best_expr)
            except:
                # Should never fail if Pareto df is loaded properly
                if pareto_df is not None:
                    raise ValueError("Pareto df properly loaded but expressions could not be loaded.")
                symbolic_model = ""
                model_size     = 0.

            try:
                # Could fail because best_expr is not defined or because simplification won't work
                simplified_symbolic_model  = Feyn.clean_sympy_expr(best_expr)
                simplified_complexity      = Feyn.complexity(simplified_symbolic_model)
            except:
                simplified_symbolic_model = ""
                simplified_complexity     = 0.

            symbolic_result = {
                'symbolic_model'            : symbolic_model,
                'model_size'                : model_size,
                'simplified_symbolic_model' : simplified_symbolic_model,
                'simplified_complexity'     : simplified_complexity,
                }
            run_result.update(symbolic_result)

            # ----- Symbolic equivalence related -----

            if pareto_df is not None:
                # assess_equivalence is error protected, it can only fail if pareto_df is not defined
                _, equivalence_report = assess_equivalence (pareto_df=pareto_df, Feynman_pb=pb, verbose=True)
            else:
                equivalence_report = {
                    'symbolic_error'                : '',
                    'symbolic_fraction'             : '',
                    'symbolic_error_is_zero'        : None,
                    'symbolic_error_is_constant'    : None,
                    'symbolic_fraction_is_constant' : None,
                    'sympy_exception'               : "NoParetoFrontFile",
                    'symbolic_solution'             : False,
                }

            run_result.update(equivalence_report)

            # ----- Numeric accuracy related -----

            # mse_test
            try:
                mse_test = assess_metric_test (pareto_df = pareto_df, Feynman_pb = pb, metric_func = metrics_utils.MSE)
                # If a Nan is returned (eg because of unprotected sqrt) go straight to except
                if np.isnan(mse_test): raise ValueError
            except:
                mse_test = np.inf

            # mae_test
            try:
                mae_test = assess_metric_test(pareto_df=pareto_df, Feynman_pb=pb, metric_func=metrics_utils.MAE)
                # If a Nan is returned (eg because of unprotected sqrt) go straight to except
                if np.isnan(mae_test): raise ValueError
            except:
                mae_test = np.inf

            # r2_test
            try:
                r2_test = assess_metric_test(pareto_df=pareto_df, Feynman_pb=pb, metric_func=metrics_utils.r2)
                # If a Nan is returned (eg because of unprotected sqrt) go straight to except
                if np.isnan(r2_test): raise ValueError
            except:
                r2_test = 0.

            # r2_zero_test
            try:
                r2_zero_test = assess_metric_test (pareto_df = pareto_df, Feynman_pb = pb, metric_func = metrics_utils.r2_zero)
                # If a Nan is returned go straight to except
                if np.isnan(r2_zero_test): raise ValueError
            except:
                r2_zero_test = 0.

            numeric_result = {
                 'mse_test'     : mse_test,
                 'mae_test'     : mae_test,
                 'r2_test'      : r2_test,
                 'r2_zero_test' : r2_zero_test,
             }
            run_result.update(numeric_result)

            # ----- Appending result -----
            all_results.append(run_result)
    else:
        print("Problem excluded.")
    # Saving at each iteration : detailed results
    results_df = results_df.from_dict(all_results)
    results_df.to_csv(PATH_RESULTS_SAVE)
    # Saving at each iteration : aggregated summary
    results_agg_df = results_df.groupby(columns_to_aggregate_on, as_index=False).aggregate(columns_aggregation_methods)
    results_agg_df = results_agg_df.set_index(results_agg_df["EQ NB"]).sort_index()
    results_agg_df.to_csv(PATH_RESULTS_SUMMARY_SAVE)
    # Saving at each iteration : aggregated summary -> essential
    results_essential_df = results_agg_df[["EQ NB", '# EVALUATIONS', 'STARTED', 'FINISHED', 'symbolic_solution', 'r2_test', 'r2_zero_test']]
    results_essential_df.to_csv(PATH_RESULTS_ESSENTIAL_SAVE)

# ----------------------- PRINTING SOME STATS -----------------------

# 95% confidence interval
# Computes 95% confidence interval
def compute_95_ci (data):
    res = np.array(st.t.interval(confidence=0.95, df=len(data)-1, loc=np.mean(data), scale=st.sem(data)))
    return res

# Total nb of runs
n_runs = len(all_results)

# Total recovery rate
all_recov_rates  = results_agg_df["symbolic_solution"]
total_recov_rate = all_recov_rates.mean()
ci_95_rr = compute_95_ci(all_recov_rates)

# Total R2
all_r2s  = results_agg_df["r2_zero_test"]
total_r2 = all_r2s.mean()
ci_95_r2 = compute_95_ci(all_r2s)

# Nb of runs successfully started
total_started = results_agg_df["STARTED"].sum()
frac_started  = total_started/n_runs

# Nb of runs successfully finished
total_finished = results_agg_df["FINISHED"].sum()
frac_finished  = total_finished/n_runs

# Nb of evaluation performed
total_evals      = results_agg_df["# EVALUATIONS"].sum()
# Total evaluations to do = ( [nb of pb] x [n trials] ) * [n evals allowed]
total_evals_todo = n_runs * fconfig.MAX_N_EVALUATIONS

t111 = time.time()
exec_time = t111 - t000

out_str = "\n\n"\
+ "Total recovery rate    = %f %%"             %(100*total_recov_rate)\
+ "\nRecovery rate 95%% CI   = %f %%  - %f %%" %(100*ci_95_rr[0], 100*ci_95_rr[1])\
+ "\nTotal R2 coef          = %f"              % (total_r2)\
+ "\nR2 coef 95%% CI         = %f - %f "       %(ci_95_r2[0], ci_95_r2[1])\
+ "\nFrac of evals allowed  = %f %%"           %(100*total_evals/total_evals_todo)\
+ "\nFrac of runs started   = %f %% (-> %i)"   %(100*frac_started , total_started )\
+ "\nFrac of runs finished  = %f %% (-> %i)"   %(100*frac_finished, total_finished)\
+ "\n\n-> Results analyis time = %.2f s"       %(exec_time)

print(out_str)

# Saving main stats
with open(PATH_RESULTS_STATS_SAVE, "w") as text_file:
    text_file.write(out_str)


