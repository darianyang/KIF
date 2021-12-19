"""
Performs the feature importance analysis for the supervised and unsupervised learning
as well as the statistical modelling package.
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
from key_interactions_finder.model_building import SupervisedModel, UnsupervisedModel
from key_interactions_finder.stat_modelling import ProteinStatModel


@dataclass
class PostProcessor(ABC):
    """Abstract base class to unify the different postprocessing types."""

    @abstractmethod
    def get_per_res_importance(self):
        """Projects feature importances onto the per-residue level"""

    def _dict_to_df_feat_importances(self, feat_importances) -> pd.DataFrame:
        """
        Convert a dictionary of features and feature importances to a dataframe of 3 columns,
        which are: residue 1 number, residue 2 number and importance score for each feature.
        Helper function for determing the per residue importances.

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
        values = df_feat_import[1]

        per_res_import = pd.concat(
            [res1, res2, values], axis=1, join="inner")
        per_res_import.columns = ["Res1", "Res2", "Score"]

        return per_res_import

    def _per_res_importance(self, per_res_import) -> dict:
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

    def _per_feature_importances_to_file(self, feature_importances: dict, out_file: str) -> None:
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

    def _per_res_importances_to_file(self, per_res_values: dict, out_file: str) -> None:
        """
        Write out a per residue importances file.

        Parameters
        ----------
        per_res_values : dict
            Dictionary of residue numbers and there scores to write to disk.

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
    """"Processes the supervised machine learning results."""

    supervised_model: Optional[SupervisedModel]
    out_dir: str = ""
    load_from_disk: bool = True
    feat_names: np.ndarray = field(init=False)
    best_models: dict = field(init=False)
    all_feature_importances: dict = field(init=False)
    per_residue_scores: dict = field(init=False)
    y_train: np.ndarray = field(init=False)
    y_eval: np.ndarray = field(init=False)
    train_data_scaled: np.ndarray = field(init=False)
    eval_data_scaled: np.ndarray = field(init=False)

    # This is called at the end of the dataclass's initialization procedure.
    def __post_init__(self):
        """Read in extra params from either the class or disk."""
        self.out_dir = _prep_out_dir(self.out_dir)

        if self.load_from_disk:
            try:
                self.best_models = self._load_models_from_disk()
                self.feat_names = np.load(
                    "temporary_files/feature_names.npy", allow_pickle=True)
                self.y_train = np.load(
                    "temporary_files/y_train.npy", allow_pickle=True)
                self.y_eval = np.load(
                    "temporary_files/y_eval.npy", allow_pickle=True)
                self.train_data_scaled = np.load(
                    "temporary_files/train_data_scaled.npy", allow_pickle=True)
                self.eval_data_scaled = np.load(
                    "temporary_files/eval_data_scaled.npy", allow_pickle=True)
            except:
                error_message = "I cannot find the files you generated from a prior " + \
                    "machine learning run, if you have already run the machine learning, " + \
                    "make sure you are inside the right working directory. You " + \
                    "should see a folder named: 'temporary_files' if you are."
                raise FileNotFoundError(error_message)

        else:
            self.feat_names = self.supervised_model.feat_names
            self.y_train = self.supervised_model.y_train
            self.y_eval = self.supervised_model.y_eval
            self.train_data_scaled = self.supervised_model.train_data_scaled
            self.eval_data_scaled = self.supervised_model.eval_data_scaled
            # need to get the .best_estimator_ attribute to match the "if" path.
            models_made = self.supervised_model.ml_models.keys()
            self.best_models = {}
            for model in models_made:
                self.best_models[model] = (
                    self.supervised_model.ml_models[model].best_estimator_)

    def _load_models_from_disk(self) -> dict:
        """
        Loads previously made machine learning models from disk.

        Returns
        ----------
        dict
            Dictionary, keys are the model name, values are the models.
        """
        best_models = {}
        for model_name in ["ada_boost", "GBoost", "random_forest"]:
            model = pickle.load(
                open(f"temporary_files/{model_name}_Model.pickle", 'rb'))
            best_models.update({model_name: model})
        return best_models

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

            # Save to Class.
            self.all_feature_importances.update(
                {model_name: sort_feat_importances})

        print("All feature importances written to disk.")

    def get_per_res_importance(self) -> None:
        """Projects feature importances onto the per-residue level"""
        # get_feature_importance has to be run before this function.
        if len(self.all_feature_importances) == 0:
            self.get_feature_importance()

        self.per_residue_scores = {}
        for model_name, feat_importances in self.all_feature_importances.items():
            per_res_import = (
                self._dict_to_df_feat_importances(feat_importances))
            spheres = self._per_res_importance(per_res_import)

            # Save to disk
            out_file = self.out_dir + \
                str(model_name) + "Per_Residue_Importances.csv"
            self._per_res_importances_to_file(
                per_res_values=spheres,
                out_file=out_file
            )

            # Save to Class.
            self.per_residue_scores.update({model_name: spheres})

        print(
            "All per residue feature importance scores were written to disk.")


@dataclass
class UnsupervisedPostProcessor(PostProcessor):
    """Processes unsupervised machine learning results."""

    unsupervised_model: Optional[UnsupervisedModel]
    out_dir: str = ""
    feat_names: np.ndarray = field(init=False)
    data_scaled: np.ndarray = field(init=False)
    all_feature_importances: dict = field(init=False)
    per_residue_scores: dict = field(init=False)

    # This is called at the end of the dataclass's initialization procedure.
    def __post_init__(self):
        """Extract items from the ML model to this class. """
        self.out_dir = _prep_out_dir(self.out_dir)

        self.feat_names = self.unsupervised_model.feat_names
        self.data_scaled = self.unsupervised_model.data_scaled
        self.ml_models = self.unsupervised_model.ml_models

    def get_feature_importance(self) -> None:
        """Gets feature importances and saves them to file if requested"""
        self.all_feature_importances = {}

        self.all_feature_importances["PCA"] = (
            self._get_pca_importances(variance_explained_cutoff=0.95))

        # If more models are to be added beyond PCA, append here.

        # Save models to disk.
        for model_name, feat_importances in self.all_feature_importances.items():
            out_file = self.out_dir + \
                str(model_name) + "_Per_Residue_Importances.csv"

            self._per_feature_importances_to_file(
                feature_importances=feat_importances,
                out_file=out_file)

        print("All feature importances were written to disk successfully.")

    def get_per_res_importance(self) -> None:
        """Projects feature importances onto the per-residue level."""
        # get_feature_importance has to be run before this function.
        if len(self.all_feature_importances) == 0:
            self.get_feature_importance()

        self.per_residue_scores = {}
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
            self.per_residue_scores.update({model_name: spheres})

        print("All per residue feature importances were written to disk successfully.")

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
        variances = self.ml_models["PCA"].explained_variance_ratio_
        components = self.ml_models["PCA"].components_

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

        # Scale sums so that new largest sum has size 1.0
        # (good for PyMOL sphere representation as well).
        max_eigen_value = max(eigenvalue_sums)
        eigenvalues_scaled = []
        for ori_eigenvalue in eigenvalue_sums:
            eigenvalues_scaled.append(ori_eigenvalue / max_eigen_value)

        pca_importances = dict(zip(self.feat_names, eigenvalues_scaled))

        print(
            "The total variance described by the principal components (PCs) used " +
            f"for feature importance analysis is: {variance_described:.1f}%. \n" +
            f"This is the first {idx_position} PCs from a total of {len(variances)} PCs."
        )

        return pca_importances


@dataclass
class StatisticalPostProcessor(PostProcessor):
    """"Processes results from the statistical analysis module."""

    stat_model: ProteinStatModel
    out_dir: str = ""

    feature_directions: list = field(init=False)
    per_residue_directions: dict = field(init=False)
    per_residue_js_distances: dict = field(init=False)
    per_residue_mutual_infos: dict = field(init=False)

    # This is called at the end of the dataclass's initialization procedure.
    def __post_init__(self):
        """Define. """
        self.out_dir = _prep_out_dir(self.out_dir)
        self.feature_directions = []
        self.per_residue_directions = {}
        self.per_residue_js_distances = {}
        self.per_residue_mutual_infos = {}

    def get_per_res_importance(self, stat_method: str) -> dict:
        """
        Projects feature importances onto the per-residue level for a single user selected
        statistical method.

        Parameters
        ----------
        stat_method : str
            Define the statistical method that should be used to generate the per
            residue importances.

        Returns
        ----------
        dict
            Dictionary of each residue and it's relative importance.

        """
        if stat_method == "jenson_shannon":
            per_res_import = (self._dict_to_df_feat_importances(
                self.stat_model.js_distances))
            self.per_residue_js_distances = (
                self._per_res_importance(per_res_import))

            out_file = self.out_dir + "Jenson_Shannon_Distances_Per_Residue.csv"
            self._per_res_importances_to_file(
                per_res_values=self.per_residue_js_distances,
                out_file=out_file
            )
            return self.per_residue_js_distances

        elif stat_method == "mutual_information":
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

        else:
            raise ValueError(
                """You did not select one of either 'jenson_shannon'
                 or 'mutual_information' for the 'stat_method' parameter.""")

    def get_probability_distributions(self,
                                      number_features: Union[int, str]
                                      ) -> Tuple[np.ndarray, dict]:
        """
        Gets the probablity distributions for each feature. Features returned
        are ordered by the jensen shannon distance scores.

        Parameters
        ----------
        number_features : int or str
            The number of features to return (those with the highest jenson-shannon
            distances taken forward).
            If "all" is used instead then all features are returned.

        Returns
        ----------
        np.ndarray
            X values between 0 and 1 to match the probability distributions.

        dict
            Nested dictionary of probabily distributions. Outer keys are the class names,
            inner keys are the feature and inner values are the probability distributions.
        """
        tot_numb_features = len(self.stat_model.js_distances.keys())

        # prevents issue if user hasn't already determined js_distances
        if tot_numb_features == 0:
            self.stat_model.calc_js_distances()
            tot_numb_features = len(self.stat_model.js_distances.keys())

        if (number_features == "all") or (number_features >= tot_numb_features):
            return self.stat_model.x_values, self.stat_model.probablity_distributions

        elif number_features < tot_numb_features:
            selected_prob_distribs = {}
            for class_name in self.stat_model.class_names:
                one_feature_prob_distribs = {}
                for feature in self.stat_model.feature_list[0:number_features]:
                    distrib = self.stat_model.probablity_distributions[class_name][feature]
                    one_feature_prob_distribs[feature] = distrib

                selected_prob_distribs[class_name] = one_feature_prob_distribs

            return self.stat_model.x_values, selected_prob_distribs

        else:
            error_message = (
                "You need to choose either an integer value or 'all' for " +
                "the parameter: 'number_features'.")
            raise ValueError(error_message)

    def estimate_feature_directions(self) -> None:
        """
        Estimate the direction each feature favours by calculating the average
        score for each feature for each class. Whatever feature has the highest
        average score

        Incredibly simple logic (but should work fine for obvious features),
        so user is warned when they use this method.
        """
        warning_message = (
            "Warning, this method is very simplistic and just calculates the average " +
            "contact score/strength for each features for both classes to determine the " +
            "direction each feature appears to favour. " +
            "You should therefore interpret these results with care..."
        )
        warnings.warn(warning_message)

        avg_contact_scores = {}
        self.feature_directions = {}
        for class_name, class_observations in self.stat_model.per_class_datasets.items():
            avg_contact_scores[class_name] = class_observations.mean()

        class_0_name = self.stat_model.class_names[0]
        class_1_name = self.stat_model.class_names[1]

        for feature_name, class_0_scores in avg_contact_scores[class_0_name].items():
            class_1_score = avg_contact_scores[class_1_name][feature_name]

            if class_0_scores >= class_1_score:
                self.feature_directions.update({feature_name: class_0_name})
            else:
                self.feature_directions.update({feature_name: class_1_name})

        out_file = self.out_dir + "feature_direction_estimates.csv"

        self._save_feature_residue_direction(
            dict_to_save=self.feature_directions,
            feature_or_residue="features",
            out_file=out_file
        )

    @staticmethod
    def _save_feature_residue_direction(
            dict_to_save: dict,
            feature_or_residue: str,
            out_file: str) -> None:
        """
        Save the estimated per feature or per residue "direction" to file.

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
