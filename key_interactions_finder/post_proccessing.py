"""
Post processes the results generated from either the
(1) machine learning (from model_building.py) or the
(2) statistical modelling (from stat_modelling.py) modules.

Provides users with the ability to:

1. Extract and/or save the per feature/interaction importances to disk.

2. Generate per residue importances from the per feature importances.
(This is done by summing all the feature importances that a residue is present in
and the normalizing the results so that the top residue has an importance of 1).

3. Obtain (and/or save) the probability distributions made for each feature.
(only available for binary classification.)

4. Estimate the "direction" each feature favors by calculating the average PyContact score
for each feature and each class (only available for binary classification).
Whatever feature has the highest average score is chosen (warning, very approximate method).
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple, Union
from abc import ABC, abstractmethod
import warnings
import csv
import pickle
import pandas as pd
import numpy as np
from key_interactions_finder.utils import _prep_out_dir
from key_interactions_finder.model_building import ClassificationModel, RegressionModel, UnsupervisedModel
from key_interactions_finder.stat_modelling import ClassificationStatModel, RegressionStatModel


@dataclass
class PostProcessor(ABC):
    """Abstract base class to unify the different postprocessing classes."""

    @abstractmethod
    def get_per_res_importance(self):
        """Projects feature importances onto the per-residue level"""

    @staticmethod
    def _dict_to_df_feat_importances(feat_importances) -> pd.DataFrame:
        """
        Convert a dictionary of features and feature importances to a dataframe of 3 columns,
        which are: (1) the first residue, (2) the second residue and (3) the importance score.
        Used as a helper function for converting from per feature scores to per residues scores.

        Parameters
        ----------
        feat_importances : dict
            Contains each feature name (keys) and their corresponding importance score (values).

        Returns
        ----------
        pd.DataFrame
            dataframe of residue numbers and scores for each feature.
        """
        df_feat_import = pd.DataFrame(feat_importances.items())
        df_feat_import_res = df_feat_import[0].str.split(" +", expand=True)

        res1, res2, values = [], [], []
        res1 = (df_feat_import_res[0].str.extract("(\d+)")).astype(int)
        res2 = (df_feat_import_res[1].str.extract("(\d+)")).astype(int)
        # absolute values required as want to be able to sum linear correlations.
        values = df_feat_import[1].abs()

        per_res_import = pd.concat(
            [res1, res2, values], axis=1, join="inner")
        per_res_import.columns = ["Res1", "Res2", "Score"]

        return per_res_import

    @staticmethod
    def _per_res_importance(per_res_import) -> dict:
        """
        Sums together all the features importances/scores to determine the per-residue value.

        Parameters
        ----------
        per_res_import : pd.DataFrame
            Dataframe with columns of both residues numbers and the importance score for
            each feature.

        Returns
        ----------
        dict
            Keys are each residue, values are the residue's relative importance.
        """
        max_res = max(per_res_import[["Res1", "Res2"]].max())
        res_ids = []
        tot_scores = []
        for i in range(1, max_res+1, 1):
            res_ids.append(i + 1)
            tot_scores.append(
                per_res_import.loc[per_res_import["Res1"] == i, "Score"].sum() +
                per_res_import.loc[per_res_import["Res2"] == i, "Score"].sum())

        # Rescale scores so that new largest has size 1.0
        # (good for PyMOL sphere representation as well).
        max_ori_score = max(tot_scores)
        tot_scores_scaled = []
        for i in range(1, max_res, 1):
            tot_scores_scaled.append(tot_scores[i] / max_ori_score)

        spheres = dict(sorted(zip(
            res_ids, tot_scores_scaled), key=lambda x: x[1], reverse=True))

        spheres = {keys: np.around(values, 5)
                   for keys, values in spheres.items()}

        return spheres

    @staticmethod
    def _per_feature_importances_to_file(feature_importances: dict, out_file: str) -> None:
        """
        Write out a per feature importances file.

        Parameters
        ----------
        feature_importances : dict
            Dictionary of feature names and there scores to write to disk.

        out_file : str
            The full path to write the file too.
        """
        with open(out_file, "w", newline="") as out:
            csv_out = csv.writer(out)
            csv_out.writerow(["Feature", "Importance"])
            for key, value in feature_importances.items():
                csv_out.writerow([key, np.around(value, 4)])
            print(f"{out_file} written to disk.")

    @staticmethod
    def _per_res_importances_to_file(per_res_values: dict, out_file: str) -> None:
        """
        Write out a per residue importances file.

        Parameters
        ----------
        per_res_values : dict
            Dictionary of residue numbers and their scores to write to disk.

        out_file : str
            The full path to write the file too.
        """
        with open(out_file, "w", newline="") as file_out:
            csv_out = csv.writer(file_out)
            csv_out.writerow(["Residue Number", "Normalised Score"])
            csv_out.writerows(per_res_values.items())
            print(f"{out_file} written to disk.")


@dataclass
class SupervisedPostProcessor(PostProcessor):
    """
    Processes the supervised machine learning results.

    Data to process can be loaded from disk or using an instance of a
    supervised model class, ("ClassificationModel" or "RegressionModel").
    See the class methods "load_models_from_instance()" and/or "load_models_from_disk"
    for further information.

    Attributes
    ----------
    out_dir : str
        Directory path to store results files to.
        Default = ""

    feat_names : np.ndarray
        All feature names/labels.

    best_models : dict
        Keys are the model name/method and values are the instance of the
        best built model.

    all_feature_importances : dict
        Nested dictionary with outer keys the model used. Inner keys
        are the feature names and values are the importances.
        Feature are ordered from most important to least.
        Generated by the 'get_feature_importance' method.

    all_per_residue_scores : dict
        Feature importances projected onto the per residue level.
        Keys are the residue numbers, values are the normalised importances.
        Generated by summing all feature importances involving a given
        residue together and then normalising.
        Generated by the 'get_per_res_importance' method.

    Methods
    -------
    load_models_from_instance(supervised_model)
        Gets the generated machine learning model data from an instance
        of either the ClassificationModel or RegressionModel class.

    load_models_from_disk(models_to_use)
        Loads the generated machine learning models from disk.

    get_feature_importance()
        Gets the feature importances and saves them to disk.

    get_per_res_importance()
        Projects feature importances onto the per-residue level.
    """
    out_dir: str = ""
    feat_names: np.ndarray = field(init=False)
    best_models: dict = field(init=False)
    all_feature_importances: dict = field(init=False)
    all_per_residue_scores: dict = field(init=False)

    # This is called at the end of the dataclass's initialization procedure.
    def __post_init__(self):
        """Prep outdir, initialise the undefined variables."""
        self.out_dir = _prep_out_dir(self.out_dir)

        self.feat_names = np.empty(shape=(0, 0))
        self.best_models = {}
        self.all_feature_importances = {}
        self.all_per_residue_scores = {}

    def load_models_from_instance(self,
                                  supervised_model: Union[ClassificationModel, RegressionModel],
                                  models_to_use: Union[str, list] = "all") -> None:
        """
        Gets the generated machine learning model data from an instance
        of either the ClassificationModel or RegressionModel class.

        Parameters
        ----------
        supervised_model : ClassificationModel, RegressionModel
            Name of the supervised model class instance used to build the ml models.

        models_to_use : str or list
            Either perform post-processing on all generated models ("all") or
            provide a list of strings of the ml models to postprocess.
            Default is "all"
        """
        self.feat_names = supervised_model.feat_names
        self.best_models = {}

        if models_to_use == "all":
            for model in supervised_model.ml_models.keys():
                self.best_models[model] = (
                    supervised_model.ml_models[model].best_estimator_)

        elif isinstance(models_to_use, list):
            for model in models_to_use:
                self.best_models[model] = (
                    supervised_model.ml_models[model].best_estimator_)

        else:
            error_message = ("For the parameter 'models_to_use', you need to choose either 'all' " +
                             "or provide a list of models you wish to use.")
            raise ValueError(error_message)

    def load_models_from_disk(self, models_to_use: list) -> None:
        """
        Loads the generated machine learning models from disk to obtain
        the models to be analysed (self.best_models) as a dictionary
        and the feature names (self.feat_names) as a numpy array.

        Parameters
        ----------
        models_to_use : list
            List of machine learning models/algorithims to do the postprocessing on.
        """
        try:
            self.feat_names = np.load(
                "temporary_files/feature_names.npy", allow_pickle=True)

            self.best_models = {}
            for model_name in models_to_use:
                model = pickle.load(
                    open(f"temporary_files/{model_name}_Model.pickle", 'rb'))
                self.best_models.update({model_name: model})

        except FileNotFoundError:
            error_message = "I cannot find the files you generated from a prior " + \
                "machine learning run, if you have already run the machine learning, " + \
                "make sure you are inside the right working directory. You " + \
                "should see a folder named: 'temporary_files' if you are."
            raise error_message

    def get_feature_importance(self) -> None:
        """Gets the feature importances and saves them to disk."""
        self.all_feature_importances = {}
        for model_name, model in self.best_models.items():
            raw_importances = list(np.around(model.feature_importances_, 8))
            feat_importances = zip(self.feat_names, raw_importances)
            sort_feat_importances = dict(sorted(
                feat_importances, key=lambda x: x[1], reverse=True))

            # Save to disk
            out_file = self.out_dir + \
                str(model_name) + "_Feature_Importances.csv"
            self._per_feature_importances_to_file(
                feature_importances=sort_feat_importances,
                out_file=out_file
            )

            # Add to the class.
            self.all_feature_importances.update(
                {model_name: sort_feat_importances})

        print("All feature importances have now been saved to disk.")

    def get_per_res_importance(self) -> None:
        """Projects feature importances onto the per-residue level"""
        # get_feature_importance has to be run before this function.
        if len(self.all_feature_importances) == 0:
            self.get_feature_importance()

        self.all_per_residue_scores = {}
        for model_name, feat_importances in self.all_feature_importances.items():
            per_res_import = (
                self._dict_to_df_feat_importances(feat_importances))
            spheres = self._per_res_importance(per_res_import)

            # Save to disk
            out_file = self.out_dir + \
                str(model_name) + "_Per_Residue_Importances.csv"
            self._per_res_importances_to_file(
                per_res_values=spheres,
                out_file=out_file
            )

            # Save to Class.
            self.all_per_residue_scores.update({model_name: spheres})

        print("All per residue importance scores have now been saved to disk.")


@dataclass
class UnsupervisedPostProcessor(PostProcessor):
    """
    Processes unsupervised machine learning results.

    Please note that there is limited support for this class as it stands.

    Attributes
    ----------
    unsupervised_model : Optional[UnsupervisedModel]
        Instance of the unsupervised model class with models already built.

    out_dir : str
        Directory path to store results files to.
        Default = ""

    all_feature_importances : dict
        Nested dictionary with outer keys the model used. Inner keys
        are the feature names and values are the importances.
        Feature are ordered from most important to least.
        Generated by the 'get_feature_importance' method.

    all_per_residue_scores : dict
        Feature importances projected onto the per residue level.
        Keys are the residue numbers, values are the normalised importances.
        Generated by summing all feature importances involving a given
        residue together and then normalising.
        Generated by the 'get_per_res_importance' method.

    Methods
    -------
    get_feature_importance()
        Gets the feature importances and saves them to disk.

    get_per_res_importance()
        Projects feature importances onto the per-residue level.
    """
    unsupervised_model: Optional[UnsupervisedModel]
    out_dir: str = ""
    all_feature_importances: dict = field(init=False)
    all_per_residue_scores: dict = field(init=False)

    # This is called at the end of the dataclass's initialization procedure.
    def __post_init__(self):
        """Only need to prepare the output directory here."""
        self.out_dir = _prep_out_dir(self.out_dir)
        self.all_per_residue_scores = {}

    def get_feature_importance(self, variance_explained_cutoff=0.95) -> None:
        """
        Gets the feature importances and saves them to disk.

        Parameters
        ----------
        variance_explained_cutoff : int
            What fraction of the variance needs to be described by the principal components (PCs)
            in order to stop including further PCs. Default is 0.95 (95%).
        """
        self.all_feature_importances = {}

        self.all_feature_importances["PCA"] = (
            self._get_pca_importances(variance_explained_cutoff))

        # If more models are to be added beyond PCA, append here.

        # Save models to disk.
        for model_name, feat_importances in self.all_feature_importances.items():
            out_file = self.out_dir + \
                str(model_name) + "_Feature_Importances.csv"

            self._per_feature_importances_to_file(
                feature_importances=feat_importances,
                out_file=out_file)

        print("All feature importances have now been saved to disk.")

    def get_per_res_importance(self) -> None:
        """Projects feature importances onto the per-residue level."""
        # get_feature_importance has to be run before this function.
        if len(self.all_feature_importances) == 0:
            self.get_feature_importance()

        self.all_per_residue_scores = {}
        for model_name, feat_importances in self.all_feature_importances.items():
            per_res_import = (
                self._dict_to_df_feat_importances(feat_importances))
            spheres = self._per_res_importance(per_res_import)

            # Save to disk
            out_file = self.out_dir + \
                str(model_name) + "_Per_Residue_Importances.csv"
            self._per_res_importances_to_file(
                per_res_values=spheres,
                out_file=out_file
            )

            # Save to Class
            self.all_per_residue_scores.update({model_name: spheres})

        print("All per residue importance scores have now been saved to disk.")

    def _get_pca_importances(self, variance_explained_cutoff: float = 0.95) -> dict:
        """
        Determine feature importances from principal component analysis (PCA).

        Basic idea is:
        1. Find the number of PCs needed to explain a given amount of variance (default = 95%).
        2. Extract the eigenvalues from each of those PCs for every feature.
        3. Take the absolute value of each eigenvalue and scale it based on the weight of
        the PC it comes from.
        4. Sum all the eigenvalues for a given feature together.
        5. Find the max scoring feature and normalise so max value = 1.
        6. Put results in a dictionary.

        Based on this dicussion:
        https://stackoverflow.com/questions/50796024/feature-variable-importance-after-a-pca-analysis

        Parameters
        ----------
        variance_explained_cutoff : int
            What fraction of the variance needs to be described by the principal components (PCs)
            in order to stop including further PCs. Default is 0.95 (95%).

        Returns
        ----------
        dict
            Dictionary of PCA calculated feature importances. Keys are feature names,
            values are normalised feature importances.
        """
        variances = self.unsupervised_model.ml_models["PCA"].explained_variance_ratio_
        components = self.unsupervised_model.ml_models["PCA"].components_

        combined_variance = variances[0]
        idx_position = 1
        while combined_variance <= variance_explained_cutoff:
            combined_variance += variances[idx_position]
            idx_position += 1

        variance_described = sum(variances[0:idx_position]) * 100
        components_keep = components[0:idx_position]

        eigenvalue_sums = []
        for idx, _ in enumerate(components_keep):
            eigenvalues = [eigenvalues[idx] for eigenvalues in components_keep]
            eigenvalues_reweighted = [(eigenvalue * variances[idx])
                                      for idx, eigenvalue in enumerate(eigenvalues)]

            eigenvalue_sums.append(np.sum(np.absolute(eigenvalues_reweighted)))

        eigenvalues_scaled = self._scale_eigenvalues(eigenvalue_sums)

        pca_importances = dict(
            zip(self.unsupervised_model.feat_names, eigenvalues_scaled))

        print(
            "The total variance described by the principal components (PCs) used " +
            f"for feature importance analysis is: {variance_described:.1f}%. This was \n" +
            f"determined from the first {idx_position} PCs from a total of {len(variances)} PCs."
        )

        return pca_importances

    @staticmethod
    def _scale_eigenvalues(eigenvalue_sums: list) -> list:
        """
        Scale the summed per feature eigenvalues so that the new largest sum has size 1.0.
        This is a good size for PyMOL sphere representation as well.

        Parameters
        ----------
        eigenvalue_sums : list
            Per feature summed eigenvalues with no scaling.

        Returns
        ----------
        list
            Per feature summed eigenvalues now scaled.
        """
        max_eigen_value = max(eigenvalue_sums)
        eigenvalues_scaled = []
        for ori_eigenvalue in eigenvalue_sums:
            eigenvalues_scaled.append(ori_eigenvalue / max_eigen_value)

        return eigenvalues_scaled


@dataclass
class StatClassificationPostProcessor(PostProcessor):
    """
    Processes results generated by the statistical analysis module for datasets with 2 classes.
    I.E., those generated by the "ClassificationStatModel".

    Attributes
    ----------
    stat_model : ClassificationStatModel
        Instance of the statistical model produced by the stat_modelling.py module.

    out_dir : str
        Directory path to store results files to.
        Default = ""

    per_residue_mutual_infos : dict
        Dictionary of each residue (keys) and it's relative importance (values) by
        summing and normalising all the per feature mutual information scores.
        Can be generated by calling the 'get_per_res_importance' method.

    per_residue_js_distances : dict
        Dictionary of each residue (keys) and it's relative importance (values) by
        summing and normalising all the per feature Jensen Shannon distances.
        Can be generated by calling the 'get_per_res_importance' method.

    feature_directions : dict
        Keys are the feature and the values are the class higher values of the feature
        are calculated to favour. Generated by calling the
        'estimate_feature_directions' method.

    Methods
    -------
    get_per_res_importance(stat_method)
        Projects feature importances onto the per-residue level for a single user selected
        statistical method.

    get_probability_distributions(number_features)
        Gets the probability distributions for each feature. The order in which features
        are returned is controlled by their Jensen-Shannon distance scores.

    estimate_feature_directions()
        Estimate the direction each feature favours by calculating the average
        score for each feature for each class. Whatever feature has the highest
        average score.
    """
    stat_model: ClassificationStatModel
    out_dir: str = ""

    per_residue_mutual_infos: dict = field(init=False)
    per_residue_js_distances: dict = field(init=False)
    feature_directions: dict = field(init=False)

    # This is called at the end of the dataclass's initialization procedure.
    def __post_init__(self):
        """Prep out_dir and initalise the variables not yet ready to be made."""
        self.out_dir = _prep_out_dir(self.out_dir)

        self.per_residue_mutual_infos = {}
        self.per_residue_js_distances = {}
        self.feature_directions = {}

    def get_per_res_importance(self, stat_method: str) -> dict:
        """
        Projects feature importances onto the per-residue level for a
        single user selected statistical method.

        Parameters
        ----------
        stat_method : str
            Define the statistical method that should be used to generate
            the per residue importances.
            "jensen_shannon" or "mutual_information" allowed.

        Returns
        ----------
        dict
            Dictionary of each residue and it's relative importance.
        """
        if stat_method == "mutual_information":
            per_res_import = (self._dict_to_df_feat_importances(
                self.stat_model.mutual_infos))
            self.per_residue_mutual_infos = (
                self._per_res_importance(per_res_import))

            out_file = self.out_dir + "Mutual_Information_Scores_Per_Residue.csv"
            self._per_res_importances_to_file(
                per_res_values=self.per_residue_mutual_infos,
                out_file=out_file
            )
            return self.per_residue_mutual_infos

        if stat_method == "jensen_shannon":
            per_res_import = (self._dict_to_df_feat_importances(
                self.stat_model.js_distances))
            self.per_residue_js_distances = (
                self._per_res_importance(per_res_import))

            out_file = self.out_dir + "Jensen_Shannon_Distance_Scores_Per_Residue.csv"
            self._per_res_importances_to_file(
                per_res_values=self.per_residue_js_distances,
                out_file=out_file
            )
            return self.per_residue_js_distances

        raise ValueError("""You did not select one of either 'jensen_shannon'
        or 'mutual_information' for the 'stat_method' parameter.""")

    def get_probability_distributions(self,
                                      number_features: Union[int, str]
                                      ) -> Tuple[np.ndarray, dict]:
        """
        Gets the probability distributions for each feature.
        If you don't ask for all features then the features returned will be the top X
        features, where X is the number you request.
        The "top features" are defined by their Jensen-Shannon distances.

        Parameters
        ----------
        number_features : int or str
            The number of features to return (those with the highest jensen-shannon
            distances taken forward).
            If "all" is used instead then all features are returned unordered.

        Returns
        ----------
        np.ndarray
            X values between 0 and 1 to match the probability distributions.

        dict
            Nested dictionary of probabily distributions. Outer keys are the class names,
            inner keys are the feature and inner values are the probability distributions.
        """
        tot_numb_features = len(self.stat_model.js_distances.keys())

        # prevents issue if user hasn't already determined js_distances.
        if tot_numb_features == 0:
            self.stat_model.calc_js_distances()
            tot_numb_features = len(self.stat_model.js_distances.keys())

        if (number_features == "all") or (number_features >= tot_numb_features):
            return self.stat_model.x_values, self.stat_model.probability_distributions

        if number_features < tot_numb_features:
            # first have to decide which prob distributions to ouput by JS distances
            features_to_output = list(self.stat_model.js_distances.keys())[
                0:number_features]
            print(features_to_output)

            selected_prob_distribs = {}
            for class_name in self.stat_model.class_names:
                one_feature_prob_distribs = {}
                for feature in features_to_output:
                    distrib = self.stat_model.probability_distributions[class_name][feature]
                    one_feature_prob_distribs[feature] = distrib

                selected_prob_distribs[class_name] = one_feature_prob_distribs

            return self.stat_model.x_values, selected_prob_distribs

        error_message = ("You need to choose either an integer value or 'all' " +
                         "for the parameter: 'number_features'.")
        raise ValueError(error_message)

    def estimate_feature_directions(self) -> None:
        """
        Estimate the "direction" each feature favours by calculating the average
        score for each feature for each class, meaning that whatever class has
        the highest average score for a feature is selected.

        Incredibly simple logic (but should work fine for obvious features),
        so user will be given a warning when they use this method.
        """
        warning_message = (
            "Warning, this method is very simplistic and just calculates the average " +
            "contact score/strength for all features for both classes to determine the " +
            "direction each feature appears to favour. " +
            "You should therefore interpret these results with care..."
        )
        warnings.warn(warning_message)

        per_class_datasets = {}
        for class_name in self.stat_model.class_names:
            per_class_datasets[class_name] = self.stat_model.scaled_dataset[(
                self.stat_model.scaled_dataset["Target"] == class_name)]

        avg_contact_scores = {}
        self.feature_directions = {}
        for class_name, class_observations in per_class_datasets.items():
            avg_contact_scores[class_name] = class_observations.mean()

        class_0_name = self.stat_model.class_names[0]
        class_1_name = self.stat_model.class_names[1]

        for feature_name, class_0_scores in avg_contact_scores[class_0_name].items():
            class_1_score = avg_contact_scores[class_1_name][feature_name]

            if class_0_scores >= class_1_score:
                self.feature_directions.update({feature_name: class_0_name})
            else:
                self.feature_directions.update({feature_name: class_1_name})

        out_file = self.out_dir + "Feature_Direction_Estimates.csv"

        self._save_feature_residue_direction(
            dict_to_save=self.feature_directions,
            feature_or_residue="features",
            out_file=out_file
        )

        print("You can access these predictions through the 'feature_directions' class attribute.")

    @staticmethod
    def _save_feature_residue_direction(
            dict_to_save: dict,
            feature_or_residue: str,
            out_file: str) -> None:
        """
        Save the estimated per feature or per residue "directions" to file.

        Parameters
        ----------
        dict_to_save : dict
            Dictionary of feature names or residue numbers (keys) vs predicted direction (values).

        feature_or_residue : str
            Define if the file to be saved is per residue or per feature.

        out_file : str
            Full path of file to write out.
        """
        with open(out_file, "w", newline="") as file_out:
            csv_out = csv.writer(file_out)

            if feature_or_residue == "features":
                csv_out.writerow(["Feature Name", "Predicted Direction"])
            elif feature_or_residue == "residues":
                csv_out.writerow(["Residue Number", "Predicted Direction"])
            else:
                raise ValueError(
                    "Only 'features' or 'residues' allowed for parameter 'feature_or_residue'."
                )

            csv_out.writerows(dict_to_save.items())
        print(f"{out_file} written to disk.")


@dataclass
class StatRegressorPostProcessor(PostProcessor):
    """
    Processes results generated by the statistical analysis module for datasets
    with a continuous target variable. Meaning those generated by the "RegressionStatModel".

    Attributes
    ----------
    stat_model : RegressionStatModel
        Instance of the statistical model produced by the stat_modelling.py module.

    out_dir : str
        Directory path to store results files to.
        Default = ""

    per_residue_mutual_infos : dict
        Dictionary of each residue (keys) and it's relative importance (values) by
        summing and normalising all the per feature mutual information scores.
        Can be generated by calling the 'get_per_res_importance' method.

    per_residue_linear_correlations : dict
        Dictionary of each residue (keys) and it's relative importance (values) by
        summing and normalising all the per feature correlation values. (The absolute value of
        each feature correlation is taken for summing together).
        Can be generated by calling the 'get_per_res_importance' method.

    Methods
    -------
    get_per_res_importance(stat_method)
        Projects feature importances onto the per-residue level for a single user selected
        statistical method.
    """
    stat_model: RegressionStatModel
    out_dir: str = ""

    per_residue_mutual_infos: dict = field(init=False)
    per_residue_linear_correlations: dict = field(init=False)

    # This is called at the end of the dataclass's initialization procedure.
    def __post_init__(self):
        """Prep out_dir and initalise the variables not yet ready to be made."""
        self.out_dir = _prep_out_dir(self.out_dir)

        self.per_residue_mutual_infos = {}
        self.per_residue_linear_correlations = {}

    def get_per_res_importance(self, stat_method: str) -> dict:
        """
        Projects feature importances onto the per-residue level for a
        single user selected statistical method.

        Parameters
        ----------
        stat_method : str
            Define the statistical method that should be used to generate
            the per residue importances.
            "mutual_information" or "linear_correlation" allowed.

        Returns
        ----------
        dict
            Dictionary of each residue and it's relative importance.
        """
        if stat_method == "mutual_information":
            per_res_import = (self._dict_to_df_feat_importances(
                self.stat_model.mutual_infos))
            self.per_residue_mutual_infos = (
                self._per_res_importance(per_res_import))

            out_file = self.out_dir + "Mutual_Information_Scores_Per_Residue.csv"
            self._per_res_importances_to_file(
                per_res_values=self.per_residue_mutual_infos,
                out_file=out_file
            )
            return self.per_residue_mutual_infos

        if stat_method == "linear_correlation":
            per_res_import = (self._dict_to_df_feat_importances(
                self.stat_model.linear_correlations))
            self.per_residue_linear_correlations = (
                self._per_res_importance(per_res_import))

            out_file = self.out_dir + "Linear_Correlation_Scores_Per_Residue.csv"
            self._per_res_importances_to_file(
                per_res_values=self.per_residue_linear_correlations,
                out_file=out_file
            )
            return self.per_residue_linear_correlations

        raise ValueError(
            """You did not select one of either 'mutual_information' or
            'linear_correlation' for the 'stat_method' parameter.""")
