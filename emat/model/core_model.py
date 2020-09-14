# -*- coding: utf-8 -*-
""" core_model.py - define coure model API"""
import os
import abc
import yaml
import pandas as pd
import numpy as np
from typing import Union, Mapping
from ..workbench.em_framework.model import AbstractModel as AbstractWorkbenchModel
from ..workbench.em_framework.evaluators import BaseEvaluator

from typing import Collection
from typing import Iterable

from ..database.database import Database
from ..scope.scope import Scope
from ..optimization.optimization_result import OptimizationResult
from ..optimization import EpsilonProgress, ConvergenceMetrics, SolutionCount
from ..util.evaluators import prepare_evaluator

from .._pkg_constants import *

from ..util.loggers import get_module_logger
_logger = get_module_logger(__name__)

class AbstractCoreModel(abc.ABC, AbstractWorkbenchModel):
    """
    An interface for using a model with EMAT.

    Individual models should be instantiated using derived
    subclasses of this abstract base class, and not using
    this class directly.

    Args:
        configuration: The configuration for this
            core model. This can be passed as a dict, or as a str
            which gives the filename of a YAML file that will be
            loaded. If there is no configuration, giving None is
            also acceptable.
        scope (Scope or str): The exploration scope, as a Scope object or as
            a str which gives the filename of a YAML file that will be
            loaded.
        safe: Load the configuration YAML file in 'safe' mode.
            This can be disabled if the configuration requires
            custom Python types or is otherwise not compatible with
            safe mode. Loading configuration files with safe mode
            off is not secure and should not be done with files from
            untrusted sources.
        db: An optional Database to store experiments and results.
        name: A name for this model, given as an alphanumeric string.
            The name is required by workbench operations.
            If not given, "EMAT" is used.
        metamodel_id: An identifier for this model, if it is a meta-model.
            Defaults to 0 (i.e., not a meta-model).
    """

    def __init__(self,
                 configuration:Union[str,Mapping,None],
                 scope:Union[Scope,str],
                 safe:bool=True,
                 db:Database=None,
                 name:str='EMAT',
                 metamodel_id:int=0,
                 ):
        if isinstance(configuration, str):
            with open(configuration, 'r') as stream:
                if safe:
                    configuration = yaml.safe_load(stream)
                else:
                    configuration = yaml.load(stream, Loader=yaml.FullLoader)
            if configuration is None:
                configuration = {}

        self.config = configuration if configuration is not None else {}
        self.db = db
        if isinstance(scope, Scope):
            self.scope = scope
        else:
            self.scope = Scope(scope)

        AbstractWorkbenchModel.__init__(self, name=name.replace('_','').replace(' ',''))
        self.uncertainties = self.scope._x_list
        self.levers = self.scope._l_list
        self.constants = self.scope._c_list
        self.outcomes = self.scope._m_list

        self.metamodel_id = metamodel_id

    def __getstate__(self):
        # don't pickle the db connection
        return dict((k, v) for (k, v) in self.__dict__.items() if (k != 'db'))

    @abc.abstractmethod
    def setup(self, params):
        """
        Configure the core model with the experiment variable values.

        This method is the place where the core model set up takes place,
        including creating or modifying files as necessary to prepare
        for a core model run.  When running experiments, this method
        is called once for each core model experiment, where each experiment
        is defined by a set of particular values for both the exogenous
        uncertainties and the policy levers.  These values are passed to
        the experiment only here, and not in the `run` method itself.
        This facilitates debugging, as the `setup` method can potentially
        be used without the `run` method, allowing the user to manually
        inspect the prepared files and ensure they are correct before
        actually running a potentially expensive model.

        Each input exogenous uncertainty or policy lever can potentially
        be used to manipulate multiple different aspects of the underlying
        core model.  For example, a policy lever that includes a number of
        discrete future network "build" options might trigger the replacement
        of multiple related network definition files.  Or, a single uncertainty
        relating to the cost of fuel might scale both a parameter linked to
        the modeled per-mile cost of operating an automobile, as well as the
        modeled total cost of fuel used by transit services.

        At the end of the `setup` method, a core model experiment should be
        ready to run using the `run` method.

        Args:
            params (dict):
                experiment variables including both exogenous
                uncertainty and policy levers
                
        Raises:
            KeyError:
                if a defined experiment variable is not supported
                by the core model        
        """     
 
    @abc.abstractmethod
    def get_experiment_archive_path(self, experiment_id=None, makedirs=False, parameters=None):
        """
        Returns a file system location to store model run outputs.

        For core models with long model run times, it is recommended
        to store the complete model run results in an archive.  This
        will facilitate adding additional performance measures to the
        scope at a later time.

        Both the scope name and experiment id can be used to create the 
        folder path. 
        
        Args:
            experiment_id (int):
                The experiment id, which is also the row id of the
                experiment in the database. If this is omitted, an
                experiment id is read or created using the parameters.
            makedirs (bool, default False):
                If this archive directory does not yet exist, create it.
            parameters (dict, optional):
                The parameters for this experiment, used to create or
                lookup an experiment id. The parameters are ignored
                if `experiment_id` is given.
                
        Returns:
            str: Experiment archive path (no trailing backslashes).
        """     
    
    @abc.abstractmethod
    def run(self):
        """
        Run the core model.

        This method is the place where the core model run takes place.
        Note that this method takes no arguments; all the input
        exogenous uncertainties and policy levers are delivered to the
        core model in the `setup` method, which will be executed prior
        to calling this method. This facilitates debugging, as the `setup`
        method can potentially be used without the `run` method, allowing
        the user to manually inspect the prepared files and ensure they
        are correct before actually running a potentially expensive model.
        When running experiments, this method is called once for each core
        model experiment, after the `setup` method completes.

        If the core model requires some post-processing by `post_process`
        method defined in this API, then when this function terminates
        the model directory should be in a state that is ready to run the
        `post_process` command next.

        Raises:
            UserWarning: If model is not properly setup
        """     
    
    def post_process(self, params, measure_names, output_path=None):
        """
        Runs post processors associated with particular performance measures.

        This method is the place to conduct automatic post-processing
        of core model run results, in particular any post-processing that
        is expensive or that will write new output files into the core model's
        output directory.  The core model run should already have
        been completed using `setup` and `run`.  If the relevant performance
        measures do not require any post-processing to create (i.e. they
        can all be read directly from output files created during the core
        model run itself) then this method does not need to be overloaded
        for a particular core model implementation.

        Args:
            params (dict):
                Dictionary of experiment variables, with keys as variable names
                and values as the experiment settings. Most post-processing
                scripts will not need to know the particular values of the
                inputs (exogenous uncertainties and policy levers), but this
                method receives the experiment input parameters as an argument
                in case one or more of these parameter values needs to be known
                in order to complete the post-processing.
            measure_names (List[str]):
                List of measures to be processed.  Normally for the first pass
                of core model run experiments, post-processing will be completed
                for all performance measures.  However, it is possible to use
                this argument to give only a subset of performance measures to
                post-process, which may be desirable if the post-processing
                of some performance measures is expensive.  Additionally, this
                method may also be called on archived model results, allowing
                it to run to generate only a subset of (probably new) performance
                measures based on these archived runs.
            output_path (str, optional):
                Path to model outputs.  If this is not given (typical for the
                initial run of core model experiments) then the local/default
                model directory is used.  This argument is provided primarily
                to facilitate post-processing archived model runs to make new
                performance measures (i.e. measures that were not in-scope when
                the core model was actually run).

        Raises:
            KeyError:
                If post process is not available for specified measure
        """
    
    @abc.abstractmethod
    def load_measures(
            self,
            measure_names: Collection[str]=None,
            *,
            rel_output_path=None,
            abs_output_path=None,
    ) -> dict:
        """
        Import selected measures from the core model.
        
        This method is the place to put code that can actually reach into
        files in the core model's run results and extract performance
        measures. It is expected that it should not do any post-processing
        of results (i.e. it should read from but not write to the model
        outputs directory).

        Imports measures from active scenario
        
        Args:
            measure_names (Collection[str]):
                Collection of measures to be loaded.
            rel_output_path, abs_output_path (str, optional):
                Path to model output locations, either relative
                to the `model_path` directory (when a subclass
                is a type that has a model path) or as an absolute
                directory.  If neither is given, the default
                value is equivalent to setting `rel_output_path` to
                'Outputs'.

        Returns:
            dict of measure name and values from active scenario
        
        Raises:
            KeyError: If load_measures is not available for specified
                measure
        """           
        

    @abc.abstractmethod
    def archive(self, params, model_results_path, experiment_id:int=0):
        """
        Copies model outputs to archive location.
        
        Args:
            params (dict): Dictionary of experiment variables
            model_results_path (str): archive path
            experiment_id (int, optional): The id number for this experiment.
        
        """

    def read_experiments(
            self,
            design_name,
            db=None,
            only_pending=False,
    ):
        """
        Reads results from a design of experiments from the database.

        Args:
            design_name (str): The name of the design to load.
            db (Database, optional): The Database from which to read experiments.
                If no db is given, the default `db` for this model is used.
            only_pending (bool, default False): If True, only pending
                experiments (which have no performance measure results
                stored in the database) are returned.

        Returns:
            pandas.DataFrame:
                A DataFrame that contains all uncertainties, levers, and measures
                for the experiments.

        Raises:
            ValueError:
                If there is no Database connection `db` set.
        """
        db = db if db is not None else self.db
        if db is None:
            raise ValueError('no database to read from')

        return self.ensure_dtypes(
            db.read_experiment_all(self.scope.name, design_name, only_pending=only_pending)
        )

    def read_experiment_parameters(
            self,
            design_name=None,
            db=None,
            only_pending=False,
            *,
            experiment_ids=None,
    ):
        """
        Reads uncertainties and levers from a design of experiments from the database.

        Args:
            design_name (str, optional): If given, only experiments
                associated with both the scope and the named design
                are returned, otherwise all experiments associated
                with the scope are returned.
            db (Database, optional): The Database from which to read experiments.
                If no db is given, the default `db` for this model is used.
            only_pending (bool, default False): If True, only pending
                experiments (which have no performance measure results
                stored in the database) are returned.
            experiment_ids (Collection, optional):
                A collection of experiment id's to load.  If given,
                both `design_name` and `only_pending` are ignored.

        Returns:
            pandas.DataFrame:
                A DataFrame that contains all uncertainties, levers, and measures
                for the experiments.

        Raises:
            ValueError:
                If `db` is not given and there is no default
                Database connection set.
        """
        db = db if db is not None else self.db

        if db is None:
            raise ValueError('no database to read from')

        return self.ensure_dtypes(
            db.read_experiment_parameters(
                self.scope.name,
                design_name,
                only_pending=only_pending,
                experiment_ids=experiment_ids,
            )
        )

    def read_experiment_measures(
            self,
            design_name,
            experiment_id=None,
            db=None,
    ):
        """
        Reads performace measures from a design of experiments from the database.

        Args:
            design_name (str): The name of the design to load.
            experiment_id (int, optional): The id of the experiment to load.
            db (Database, optional): The Database from which to read experiment(s).
                If no db is given, the default `db` for this model is used.

        Returns:
            pandas.DataFrame:
                A DataFrame that contains all uncertainties, levers, and measures
                for the experiments.

        Raises:
            ValueError:
                If `db` is not given and there is no default
                Database connection set.
        """
        db = db if db is not None else self.db

        if db is None:
            raise ValueError('no database to read from')

        measures =  self.ensure_dtypes(
            db.read_experiment_measures(self.scope.name, design_name, experiment_id)
        )
        
        # only return measures within scope
        measures = measures[[i for i in self.scope.get_measure_names()
                             if i in measures.columns]]
        
        return measures
        

    def ensure_dtypes(self, df:pd.DataFrame):
        """
        Convert columns of dataframe to correct dtype as needed.

        Args:
            df (pandas.DataFrame): A dataframe with column names
                that are uncertainties, levers, or measures.

        Returns:
            pandas.DataFrame:
                The same data as input, but with dtypes as appropriate.
        """
        return self.scope.ensure_dtypes(df)

    def design_experiments(self, *args, **kwargs):
        """
        Create a design of experiments based on this model.

        Args:
            n_samples_per_factor (int, default 10): The number of samples in the
                design per random factor.
            n_samples (int or tuple, optional): The total number of samples in the
                design.  If `jointly` is False, this is the number of samples in each
                of the uncertainties and the levers, the total number of samples will
                be the square of this value.  Give a 2-tuple to set values for
                uncertainties and levers respectively, to set them independently.
                If this argument is given, it overrides `n_samples_per_factor`.
            random_seed (int or None, default 1234): A random seed for reproducibility.
            db (Database, optional): If provided, this design will be stored in the
                database indicated.  If not provided, the `db` for this model will
                be used, if one is set.
            design_name (str, optional): A name for this design, to identify it in the
                database. If not given, a unique name will be generated based on the
                selected sampler.
            sampler (str or AbstractSampler, default 'lhs'): The sampler to use for this
                design.  Available pre-defined samplers include:
                    - 'lhs': Latin Hypercube sampling
                    - 'ulhs': Uniform Latin Hypercube sampling, which ignores defined
                        distribution shapes from the scope and samples everything
                        as if it was from a uniform distribution
                    - 'mc': Monte carlo sampling
                    - 'uni': Univariate sensitivity testing, whereby experiments are
                        generated setting each parameter individually to minimum and
                        maximum values (for numeric dtypes) or all possible values
                        (for boolean and categorical dtypes).  Note that designs for
                        univariate sensitivity testing are deterministic and the number
                        of samples given is ignored.
            sample_from ('all', 'uncertainties', or 'levers'): Which scope components
                from which to sample.  Components not sampled are set at their default
                values in the design.
            jointly (bool, default True): Whether to sample jointly all uncertainties
                and levers in a single design, or, if False, to generate separate samples
                for levers and uncertainties, and then combine the two in a full-factorial
                manner.  This argument has no effect unless `sample_from` is 'all'.
                Note that setting `jointly` to False may produce a very large design,
                as the total number of experiments will be the product of the number of
                experiments for the levers and the number of experiments for the
                uncertainties, which are set separately (i.e. if `n_samples` is given,
                the total number of experiments is the square of that value).

        Returns:
            pandas.DataFrame: The resulting design.
        """
        if 'scope' in kwargs:
            kwargs.pop('scope')

        if 'db' not in kwargs:
            kwargs['db'] = self.db

        from ..experiment import experimental_design
        return experimental_design.design_experiments(self.scope, *args, **kwargs)

    def run_experiments(
            self,
            design:pd.DataFrame=None,
            evaluator=None,
            *,
            design_name=None,
            db=None,
    ):
        """
        Runs a design of combined experiments using this model.

        A combined experiment includes a complete set of input values for
        all exogenous uncertainties (a Scenario) and all policy levers
        (a Policy). Unlike the perform_experiments function in the EMA Workbench,
        this method pairs each Scenario and Policy in sequence, instead
        of running all possible combinations of Scenario and Policy.
        This change ensures compatibility with the EMAT database modules, which
        preserve the complete set of input information (both uncertainties
        and levers) for each experiment.  To conduct a full cross-factorial set
        of experiments similar to the default settings for EMA Workbench,
        use a factorial design, by setting the `jointly` argument for the
        `design_experiments` to False, or by designing experiments outside
        of EMAT with your own approach.

        Args:
            design (pandas.DataFrame, optional): experiment definitions
                given as a DataFrame, where each exogenous uncertainties and
                policy levers is given as a column, and each row is an experiment.
            evaluator (emat.workbench.Evaluator, optional): Optionally give an
                evaluator instance.  If not given, a default SequentialEvaluator
                will be instantiated.
            design_name (str, optional): The name of a design of experiments to
                load from the database.  This design is only used if
                `design` is None.
            db (Database, optional): The database to use for loading and saving experiments.
                If none is given, the default database for this model is used.
                If there is no default db, and none is given here,
                the results are not stored in a database. Set to False to explicitly
                not use the default database, even if it exists.

        Returns:
            pandas.DataFrame:
                A DataFrame that contains all uncertainties, levers, and measures
                for the experiments.

        Raises:
            ValueError:
                If there are no experiments defined.  This includes
                the situation where `design` is given but no database is
                available.

        """

        from ..workbench import Scenario, Policy, perform_experiments

        # catch user gives only a design, not experiment_parameters
        if isinstance(design, str) and design_name is None:
            design_name, design = design, None

        if design_name is None and design is None:
            raise ValueError(f"must give design_name or design")

        if db is None:
            db = self.db

        if design_name is not None and design is None:
            if not db:
                raise ValueError(f'cannot load design "{design_name}", there is no db')
            design = db.read_experiment_parameters(self.scope.name, design_name)

        if design.empty:
            raise ValueError(f"no experiments available")

        scenarios = [
            Scenario(**dict(zip(self.scope._get_uncertainty_and_constant_names(), i)))
            for i in design[self.scope._get_uncertainty_and_constant_names()].itertuples(index=False,
                                                                           name='ExperimentX')
        ]

        policies = [
            Policy(f"Incognito{n}", **dict(zip(self.scope.get_lever_names(), i)))
            for n,i in enumerate(design[self.scope.get_lever_names()].itertuples(index=False,
                                                                                 name='ExperimentL'))
        ]

        evaluator = prepare_evaluator(evaluator, self)

        callback = None
        if db is not None and hasattr(db, 'callback_factory'):
            callback = db.callback_factory(
                scope=self.scope,
                design_name=design_name,
            )

        with evaluator:
            experiments, outcomes = perform_experiments(
                self,
                scenarios=scenarios,
                policies=policies,
                zip_over={'scenarios', 'policies'},
                evaluator=evaluator,
                callback=callback,
            )
        experiments.index = design.index



        outcomes = pd.DataFrame.from_dict(outcomes)
        outcomes.index = design.index

        if db:
            db.write_experiment_measures(self.scope.name, self.metamodel_id, outcomes)

        # Put constants back into experiments
        experiments_ = experiments.drop(columns=['scenario', 'policy', 'model'])
        for i in self.scope.get_constants():
            experiments_[i.name] = i.value

        result = self.ensure_dtypes(pd.concat([
            experiments_,
            outcomes
        ], axis=1, sort=False))
        from ..experiment.experimental_design import ExperimentalDesign
        result = ExperimentalDesign(result)
        result.scope = self.scope
        result.name = getattr(design, 'name', None)
        result.sampler_name = getattr(design, 'sampler_name', None)
        return result

    def run_reference_experiment(
            self,
            evaluator=None,
            *,
            db=None,
    ):
        """
        Runs a reference experiment using this model.

        This single experiment includes a complete set of input values for
        all exogenous uncertainties (a Scenario) and all policy levers
        (a Policy). Each is set to the default value indicated by the scope.

        Args:
            evaluator (emat.workbench.Evaluator, optional): Optionally give an
                evaluator instance.  If not given, a default SequentialEvaluator
                will be instantiated.
            db (Database, optional): The database to use for loading and saving experiments.
                If none is given, the default database for this model is used.
                If there is no default db, and none is given here,
                the results are not stored in a database. Set to False to explicitly
                not use the default database, even if it exists.

        Returns:
            pandas.DataFrame:
                A DataFrame that contains all uncertainties, levers, and measures
                for the experiments.

        """
        if db is None:
            db = self.db
        ref = self.design_experiments(sampler='ref', db=db)
        return self.run_experiments(ref, evaluator=evaluator, db=db)

    def create_metamodel_from_data(
            self,
            experiment_inputs:pd.DataFrame,
            experiment_outputs:pd.DataFrame,
            output_transforms: dict = None,
            metamodel_id:int = None,
            include_measures = None,
            exclude_measures = None,
            db = None,
            random_state = None,
            experiment_stratification = None,
            suppress_converge_warnings = False,
            regressor = None,
    ):
        """
        Create a MetaModel from a set of input and output observations.

        Args:
            experiment_inputs (pandas.DataFrame): This dataframe
                should contain all of the experimental inputs, including
                values for each uncertainty, level, and constant.
            experiment_outputs (pandas.DataFrame): This dataframe
                should contain all of the experimental outputs, including
                a column for each performance measure. The index
                for the outputs should match the index for the
                `experiment_inputs`, so that the I-O matches row-by-row.
            output_transforms (dict): Deprecated.  Specify the
                output transforms directly in the scope instead.
            metamodel_id (int, optional): An identifier for this meta-model.
                If not given, a unique id number will be created randomly.
            include_measures (Collection[str], optional): If provided, only
                output performance measures with names in this set will be included.
            exclude_measures (Collection[str], optional): If provided, only
                output performance measures with names not in this set will be included.
            db (Database, optional): The database to use for loading and saving metamodels.
                If none is given, the default database for this model is used.
                If there is no default db, and none is given here,
                the metamodel is not stored in a database.
            random_state (int, optional): A random state to use in the metamodel
                regression fitting.
            experiment_stratification (pandas.Series, optional):
                A stratification of experiments, used in cross-validation.
            suppress_converge_warnings (bool, default False):
                Suppress convergence warnings during metamodel fitting.
            regressor (Estimator, optional): A scikit-learn estimator implementing a
                multi-target regression.  If not given, a detrended simple Gaussian
                process regression is used.

        Returns:
            MetaModel:
                a callable object that, when called as if a
                function, accepts keyword arguments as inputs and
                returns a dictionary of (measure name: value) pairs.
        """
        from .meta_model import create_metamodel
        return create_metamodel(
            scope=self.scope,
            experiments=pd.concat([experiment_inputs, experiment_outputs], axis=1),
            metamodel_id=metamodel_id,
            db=db,
            include_measures=include_measures,
            exclude_measures=exclude_measures,
            random_state=random_state,
            experiment_stratification=experiment_stratification,
            suppress_converge_warnings=suppress_converge_warnings,
            regressor=regressor,
            name=None,
        )

    def create_metamodel_from_design(
            self,
            design_name:str,
            metamodel_id:int = None,
            include_measures=None,
            exclude_measures=None,
            db=None,
            random_state=None,
            suppress_converge_warnings=False,
            regressor=None,
    ):
        """
        Create a MetaModel from a set of input and output observations.

        Args:
            design_name (str): The name of the design to use.
            metamodel_id (int, optional): An identifier for this meta-model.
                If not given, a unique id number will be created randomly.
            include_measures (Collection[str], optional): If provided, only
                output performance measures with names in this set will be included.
            exclude_measures (Collection[str], optional): If provided, only
                output performance measures with names not in this set will be included.
            random_state (int, optional): A random state to use in the metamodel
                regression fitting.
            suppress_converge_warnings (bool, default False):
                Suppress convergence warnings during metamodel fitting.
            regressor (Estimator, optional): A scikit-learn estimator implementing a
                multi-target regression.  If not given, a detrended simple Gaussian
                process regression is used.

        Returns:
            MetaModel:
                a callable object that, when called as if a
                function, accepts keyword arguments as inputs and
                returns a dictionary of (measure name: value) pairs.

        Raises:
            ValueError: If the named design still has pending experiments.
        """
        db = db if db is not None else self.db

        if db is None:
            raise ValueError("db is None")

        check_df = db.read_experiment_parameters(self.scope.name, design_name, only_pending=True)
        if not check_df.empty:
            from ..exceptions import PendingExperimentsError
            raise PendingExperimentsError(f'design "{design_name}" has pending experiments')

        experiment_inputs = db.read_experiment_parameters(self.scope.name, design_name)
        experiment_outputs = db.read_experiment_measures(self.scope.name, design_name)

        transforms = {
            i.name: i.metamodeltype
            for i in self.scope.get_measures()
        }

        return self.create_metamodel_from_data(
            experiment_inputs,
            experiment_outputs,
            transforms,
            metamodel_id=metamodel_id,
            include_measures=include_measures,
            exclude_measures=exclude_measures,
            db=db,
            random_state=random_state,
            suppress_converge_warnings=suppress_converge_warnings,
            regressor=regressor,
        )

    def create_metamodel_from_designs(
            self,
            design_names:str,
            metamodel_id:int = None,
            include_measures=None,
            exclude_measures=None,
            db=None,
            random_state=None,
            suppress_converge_warnings=False,
    ):
        """
        Create a MetaModel from multiple sets of input and output observations.

        Args:
            design_names (Collection[str]): The names of the designs to use.
            metamodel_id (int, optional): An identifier for this meta-model.
                If not given, a unique id number will be created randomly.
            include_measures (Collection[str], optional): If provided, only
                output performance measures with names in this set will be included.
            exclude_measures (Collection[str], optional): If provided, only
                output performance measures with names not in this set will be included.
            random_state (int, optional): A random state to use in the metamodel
                regression fitting.
            suppress_converge_warnings (bool, default False):
                Suppress convergence warnings during metamodel fitting.

        Returns:
            MetaModel:
                a callable object that, when called as if a
                function, accepts keyword arguments as inputs and
                returns a dictionary of (measure name: value) pairs.

        Raises:
            ValueError: If the named design still has pending experiments.
        """
        db = db if db is not None else self.db

        if db is not None:
            for design_name in design_names:
                check_df = db.read_experiment_parameters(self.scope.name, design_name, only_pending=True)
                if not check_df.empty:
                    from ..exceptions import PendingExperimentsError
                    raise PendingExperimentsError(f'design "{design_name}" has pending experiments')

        experiment_inputs = []
        for design_name in design_names:
            f = db.read_experiment_parameters(self.scope.name, design_name)
            f['_design_'] = design_name
            experiment_inputs.append(f)
        experiment_inputs = pd.concat(experiment_inputs)

        experiment_outputs = []
        for design_name in design_names:
            f =  db.read_experiment_measures(self.scope.name, design_name)
            # f['_design_'] = design_name
            experiment_outputs.append(f)
        experiment_outputs = pd.concat(experiment_outputs)

        transforms = {
            i.name: i.metamodeltype
            for i in self.scope.get_measures()
        }

        return self.create_metamodel_from_data(
            experiment_inputs.drop('_design_', axis=1),
            experiment_outputs,
            transforms,
            metamodel_id=metamodel_id,
            include_measures=include_measures,
            exclude_measures=exclude_measures,
            db=db,
            random_state=random_state,
            experiment_stratification=experiment_inputs['_design_'],
            suppress_converge_warnings=suppress_converge_warnings,
        )


    def feature_scores(
            self,
            design,
            return_type='styled',
            random_state=None,
            cmap='viridis',
            measures=None,
    ):
        """
        Calculate feature scores based on a design of experiments.

        This method is provided as a convenient pass-through to the
        `feature_scores` function in the `analysis` sub-package, using
        the scope and database attached to this model.

        Args:
            design (str or pandas.DataFrame): The name of the design
                of experiments to use for feature scoring, or a single
                pandas.DataFrame containing the experimental design and
                results.
            return_type ({'styled', 'figure', 'dataframe'}):
                The format to return, either a heatmap figure as an SVG
                render in and xmle.Elem, or a plain pandas.DataFrame,
                or a styled dataframe.
            random_state (int or numpy.RandomState, optional):
                Random state to use.
            cmap (string or colormap, default 'viridis'): matplotlib
                colormap to use for rendering.
            measures (Collection, optional): The performance measures
                on which feature scores are to be generated.  By default,
                all measures are included.

        Returns:
            xmle.Elem or pandas.DataFrame:
                Returns a rendered SVG as xml, or a DataFrame,
                depending on the `return_type` argument.

        This function internally uses feature_scoring from the EMA Workbench, which in turn
        scores features using the "extra trees" regression approach.
        """
        from ..analysis.feature_scoring import feature_scores
        return feature_scores(
            self.scope,
            design=design,
            return_type=return_type,
            db=self.db,
            random_state=random_state,
            cmap=cmap,
            measures=measures,
        )

    def get_feature_scores(self, *args, **kwargs):
        """
        Deprecated, use `Model.feature_scores`.
        """
        # for compatability with prior versions of TMIP-EMAT
        return self.feature_scores(*args, **kwargs)

    def _common_optimization_setup(
            self,
            epsilons=0.1,
            convergence='default',
            display_convergence=True,
            evaluator=None,
    ):
        import numbers
        if isinstance(epsilons, numbers.Number):
            epsilons = [epsilons]*len(self.outcomes)

        if convergence == 'default':
            convergence = ConvergenceMetrics(
                EpsilonProgress(),
                SolutionCount(),
            )

        if display_convergence and isinstance(convergence, ConvergenceMetrics):
            from IPython.display import display
            display(convergence)

        evaluator = prepare_evaluator(evaluator, self)

        return epsilons, convergence, display_convergence, evaluator

    def optimize(
            self,
            searchover='levers',
            evaluator=None,
            nfe=10000,
            convergence='default',
            display_convergence=True,
            convergence_freq=100,
            constraints=None,
            reference=None,
            reverse_targets=False,
            algorithm=None,
            epsilons='auto',
            min_epsilon=0.1,
            cache_dir=None,
            cache_file=None,
            check_extremes=False,
            **kwargs,
    ):
        """
        Perform multi-objective optimization over levers or uncertainties.

        The targets for the multi-objective optimization (i.e. whether each
        individual performance measures is to be maximized or minimized) are
        read from the model's scope.

        Args:
            searchover ({'levers', 'uncertainties'}):
                Which group of inputs to search over.  The other group
                will be set at their default values, unless other values
                are provided in the `reference` argument.
            evaluator (Evaluator, optional): The evaluator to use to
                run the model. If not given, a SequentialEvaluator will
                be created.
            nfe (int, default 10_000): Number of function evaluations.
                This generally needs to be fairly large to achieve stable
                results in all but the most trivial applications.
            convergence ('default', None, or emat.optimization.ConvergenceMetrics):
                A convergence display during optimization.  The default
                value is to report the epsilon-progress (the number of
                solutions that ever enter the candidate pool of non-dominated
                solutions) and the number of solutions remaining in that candidate
                pool.  Pass `None` explicitly to disable convergence tracking.
            display_convergence (bool, default True): Whether to automatically
                display figures that dynamically track convergence.  Set to
                `False` if you are not using this method within a Jupyter
                interactive environment.
            convergence_freq (int, default 100): How frequently to update the
                convergence measures.  There is some computational overhead to
                these convergence updates, so setting a value too small may
                noticeably slow down the process.
            constraints (Collection[Constraint], optional):
                Solutions will be constrained to only include values that
                satisfy these constraints. The constraints can be based on
                the search parameters (levers or uncertainties, depending on the
                value given for `searchover`), or performance measures, or
                some combination thereof.
            reference (Mapping): A set of values for the non-active inputs,
                i.e. the uncertainties if `searchover` is 'levers', or the
                levers if `searchover` is 'uncertainties'.  Any values not
                set here revert to the default values identified in the scope.
            reverse_targets (bool, default False): Whether to reverse the
                optimization targets given in the scope (i.e., changing
                minimize to maximize, or vice versa).  This will result in
                the optimization searching for the worst outcomes, instead of
                the best outcomes.
            algorithm (platypus.Algorithm, optional): Select an
                algorithm for multi-objective optimization.  The default
                algorithm is EpsNSGAII. See `platypus` documentation for details.
            epsilons (float or array-like): Used to limit the number of
                distinct solutions generated.  Set to a larger value to get
                fewer distinct solutions.
            cache_dir (path-like, optional): A directory in which to
                cache results.  Most of the arguments will be hashed
                to develop a unique filename for these results, making this
                generally safer than `cache_file`.
            cache_file (path-like, optional): A file into which to
                cache results.  If this file exists, the contents of the
                file will be loaded and all other arguments are ignored.
                Use with great caution.
            kwargs: Any additional arguments will be passed on to the
                platypus algorithm.

        Returns:
            emat.OptimizationResult:
                The set of non-dominated solutions found.
                When `convergence` is given, the convergence measures are
                included, as a pandas.DataFrame in the `convergence` attribute.
        """
        from ..util.disk_cache import load_cache_if_available, save_cache
        if isinstance(algorithm, str) or algorithm is None:
            alg = algorithm
        else:
            alg = algorithm.__name__

        if reference is not None:
            from ..workbench import Policy, Scenario
            if searchover == 'levers' and not isinstance(reference, Scenario):
                reference = Scenario("ReferenceScenario", **reference)
            elif searchover == 'uncertainties' and not isinstance(reference, Policy):
                reference = Policy("ReferencePolicy", **reference)
        else:
            if searchover == 'levers':
                reference = self.scope.default_scenario()
            elif searchover == 'uncertainties':
                reference = self.scope.default_policy()

        x, cache_file = load_cache_if_available(
            cache_file=cache_file,
            cache_dir=cache_dir,
            searchover=searchover,
            nfe=nfe,
            convergence=convergence,
            convergence_freq=convergence_freq,
            constraints=constraints,
            reference=reference,
            reverse_targets=reverse_targets,
            algorithm=alg,
            epsilons=epsilons,
        )

        if x is None:
            epsilons, convergence, display_convergence, evaluator = self._common_optimization_setup(
                epsilons, convergence, display_convergence, evaluator
            )

            if reverse_targets:
                for k in self.scope.get_measures():
                    k.kind_original = k.kind
                    k.kind = k.kind * -1

            try:
                with evaluator:

                    if epsilons == 'auto':
                        from ..workbench import perform_experiments
                        if searchover == 'levers':
                            _, trial_outcomes = perform_experiments(
                                self,
                                scenarios=reference,
                                policies=30,
                                evaluator=evaluator,
                            )
                        else:
                            _, trial_outcomes = perform_experiments(
                                self,
                                scenarios=30,
                                policies=reference,
                                evaluator=evaluator,
                            )
                        epsilons = [max(min_epsilon, np.std(trial_outcomes[mn]) / 20) for mn in self.scope.get_measure_names()]

                    results = evaluator.optimize(
                        searchover=searchover,
                        reference=reference,
                        nfe=nfe,
                        constraints=constraints,
                        convergence=convergence,
                        convergence_freq=convergence_freq,
                        epsilons=epsilons,
                        **kwargs,
                    )

                    if isinstance(results, tuple) and len(results) == 2:
                        results, result_convergence = results
                    else:
                        result_convergence = None

                    # Put constants back in to results
                    for i in self.scope.get_constants():
                        results[i.name] = i.value

                    results = self.ensure_dtypes(results)
                    x = OptimizationResult(results, result_convergence, scope=self.scope)

                    if searchover == 'levers':
                        x.scenarios = reference
                    elif searchover == 'uncertainties':
                        x.policies = reference

                    if check_extremes:
                        x.check_extremes(
                            self,
                            1 if check_extremes is True else check_extremes,
                            evaluator=evaluator,
                            searchover=searchover,
                            robust=False,
                        )

            finally:
                if reverse_targets:
                    for k in self.scope.get_measures():
                        k.kind = k.kind_original
                        del k.kind_original


        elif display_convergence:
            _, convergence, display_convergence, _ = self._common_optimization_setup(
                None, convergence, display_convergence, False
            )
            for c in convergence:
                try:
                    c.rebuild(x.convergence)
                except KeyboardInterrupt:
                    raise
                except:
                    pass

        x.cache_file = cache_file
        save_cache(x, cache_file)
        return x

    def robust_optimize(
            self,
            robustness_functions,
            scenarios,
            evaluator=None,
            nfe=10000,
            convergence='default',
            display_convergence=True,
            convergence_freq=100,
            constraints=None,
            epsilons=0.1,
            cache_dir=None,
            cache_file=None,
            algorithm=None,
            check_extremes=False,
            **kwargs,
    ):
        """
        Perform robust optimization.

        The robust optimization generally a multi-objective optimization task.
        It is undertaken using statistical measures of outcomes evaluated across
        a number of scenarios, instead of using the individual outcomes themselves.
        For each candidate policy, the model is evaluated against all of the considered
        scenarios, and then the robustness measures are evaluated using the
        set of outcomes from the original runs.  The robustness measures
        are aggregate measures that are computed from a set of outcomes.
        For example, this may be expected value, median, n-th percentile,
        minimum, or maximum value of any individual outcome.  It is also
        possible to have joint measures, e.g. expected value of the larger
        of outcome 1 or outcome 2.

        Each robustness function is indicated as a maximization or minimization
        target, where higher or lower values are better, respectively.
        The optimization process then tries to identify one or more
        non-dominated solutions for the possible policy levers.

        Args:
            robustness_functions (Collection[Measure]): A collection of
                aggregate statistical performance measures.
            scenarios (int or Collection): A collection of scenarios to
                use in the evaluation(s), or give an integer to generate
                that number of random scenarios.
            evaluator (Evaluator, optional): The evaluator to use to
                run the model. If not given, a SequentialEvaluator will
                be created.
            nfe (int, default 10_000): Number of function evaluations.
                This generally needs to be fairly large to achieve stable
                results in all but the most trivial applications.
            convergence ('default', None, or emat.optimization.ConvergenceMetrics):
                A convergence display during optimization.
            display_convergence (bool, default True): Automatically display
                the convergence metric figures when optimizing.
            convergence_freq (int, default 100): The frequency at which
                convergence metric figures are updated.
            constraints (Collection[Constraint], optional)
                Solutions will be constrained to only include values that
                satisfy these constraints. The constraints can be based on
                the policy levers, or on the computed values of the robustness
                functions, or some combination thereof.
            epsilons (float or array-like): Used to limit the number of
                distinct solutions generated.  Set to a larger value to get
                fewer distinct solutions.
            cache_dir (path-like, optional): A directory in which to
                cache results.  Most of the arguments will be hashed
                to develop a unique filename for these results, making this
                generally safer than `cache_file`.
            cache_file (path-like, optional): A file into which to
                cache results.  If this file exists, the contents of the
                file will be loaded and all other arguments are ignored.
                Use with great caution.
            algorithm (platypus.Algorithm or str, optional): Select an
                algorithm for multi-objective optimization.  The algorithm can
                be given directly, or named in a string. See `platypus`
                documentation for details.
            check_extremes (bool or int, default False): Conduct additional
                evaluations, setting individual policy levers to their
                extreme values, for each candidate Pareto optimal solution.
            kwargs: any additional arguments will be passed on to the
                platypus algorithm.

        Returns:
            emat.OptimizationResult:
                The set of non-dominated solutions found.
                When `convergence` is given, the convergence measures are
                included, as a pandas.DataFrame in the `convergence` attribute.
        """
        from ..optimization.optimize import robust_optimize

        from ..util.disk_cache import load_cache_if_available, save_cache
        if isinstance(algorithm, str) or algorithm is None:
            alg = algorithm
        else:
            alg = algorithm.__name__
        result, cache_file = load_cache_if_available(
            cache_file=cache_file,
            cache_dir=cache_dir,
            scenarios=scenarios,
            convergence=convergence,
            convergence_freq=convergence_freq,
            constraints=constraints,
            epsilons=epsilons,
            nfe=nfe,
            robustness_functions=robustness_functions,
            alg=alg,
            check_extremes=check_extremes,
        )

        if result is None:
            result = robust_optimize(
                self,
                robustness_functions,
                scenarios,
                evaluator=evaluator,
                nfe=nfe,
                convergence=convergence,
                display_convergence=display_convergence,
                convergence_freq=convergence_freq,
                constraints=constraints,
                epsilons=epsilons,
                check_extremes=check_extremes,
                **kwargs,
            )
        elif display_convergence:
            _, convergence, display_convergence, _ = self._common_optimization_setup(
                None, convergence, display_convergence, False
            )
            for c in convergence:
                try:
                    c.rebuild(result.convergence)
                except KeyboardInterrupt:
                    raise
                except:
                    pass

        result.cache_file = cache_file
        save_cache(result, cache_file)
        return result

    def robust_evaluate(
            self,
            robustness_functions,
            scenarios,
            policies,
            evaluator=None,
            cache_dir=None,
    ):
        """
        Perform robust evaluation(s).

        The robust evaluation is used to generate statistical measures
        of outcomes, instead of generating the individual outcomes themselves.
        For each policy, the model is evaluated against all of the considered
        scenarios, and then the robustness measures are evaluated using the
        set of outcomes from the original runs.  The robustness measures
        are aggregate measures that are computed from a set of outcomes.
        For example, this may be expected value, median, n-th percentile,
        minimum, or maximum value of any individual outcome.  It is also
        possible to have joint measures, e.g. expected value of the larger
        of outcome 1 or outcome 2.

        Args:
            robustness_functions (Collection[Measure]): A collection of
                aggregate statistical performance measures.
            scenarios (int or Collection): A collection of scenarios to
                use in the evaluation(s), or give an integer to generate
                that number of random scenarios.
            policies (int, or collection): A collection of policies to
                use in the evaluation(s), or give an integer to generate
                that number of random policies.
            evaluator (Evaluator, optional): The evaluator to use to
                run the model. If not given, a SequentialEvaluator will
                be created.
            cache_dir (path-like, optional): A directory in which to
                cache results.

        Returns:
            pandas.DataFrame: The computed value of each item
                in `robustness_functions`, for each policy in `policies`.
        """
        robust_results = None
        cache_file = None
        if cache_dir is not None:
            try:
                from ..util.hasher import hash_it
                hh = hash_it(
                    scenarios,
                    policies,
                    robustness_functions,
                )
                os.makedirs(os.path.join(cache_dir,hh[2:4],hh[4:6]), exist_ok=True)
                cache_file = os.path.join(cache_dir,hh[2:4],hh[4:6],hh[6:]+".gz")
                if os.path.exists(cache_file):
                    _logger.debug(f"loading from cache_file={cache_file}")
                    from ..util.filez import load
                    robust_results = load(cache_file)
                    cache_file = None
            except KeyboardInterrupt:
                raise
            except:
                import warnings, traceback
                warnings.warn('unable to manage cache')
                traceback.print_exc()

        if robust_results is None:
            if evaluator is None:
                from ..workbench.em_framework import SequentialEvaluator
                evaluator = SequentialEvaluator(self)

            if not isinstance(evaluator, BaseEvaluator):
                from dask.distributed import Client
                if isinstance(evaluator, Client):
                    from ..workbench.em_framework.ema_distributed import DistributedEvaluator
                    evaluator = DistributedEvaluator(self, client=evaluator)

            from ..workbench.em_framework.samplers import sample_uncertainties, sample_levers

            if isinstance(scenarios, int):
                n_scenarios = scenarios
                scenarios = sample_uncertainties(self, n_scenarios)

            with evaluator:
                robust_results = evaluator.robust_evaluate(
                    robustness_functions,
                    scenarios,
                    policies,
                )

            robust_results = self.ensure_dtypes(robust_results)

        if cache_file is not None:
            from ..util.filez import save
            save(robust_results, cache_file, overwrite=True)
            with open(cache_file.replace('.gz','.info.txt'), 'wt') as notes:
                print("scenarios=", scenarios, file=notes)
                print("robustness_functions=", robustness_functions, file=notes)
                print("policies=", policies, file=notes)

        return robust_results

    def io_experiment(self, params):
        """
        Run an experiment, and return a dictionary of inputs and outputs together.

        Args:
            params: dict

        Returns:
            dict
        """
        out = self.run_experiment(params).copy()
        out.update(params)
        return out