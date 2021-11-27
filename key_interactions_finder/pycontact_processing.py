"""
Reformats PyContact Generated Files for easier processing with Python.
"""

import os
import pandas as pd
import numpy as np
import re
# A series of functions to assist with preprocessing the pycontact generated dataset.
# https://numpydoc.readthedocs.io/en/latest/format.html

# Generally speaking, seems to be okay.


class PyContactInitializer():
    """Class for converting PyContact generated files to a Pandas readable format."""

    def __init__(self):
        return None

    def process_pycontact_files(self, pycontact_files, base_name, in_dir="", out_dir="", multiple_files=False):
        """
        Takes a single PyContact file or list of PyContact files and returns a cleaned df.

        Parameters
        ----------
        pycontact_files : str or list
            str or list of input files names (for the same system) to process.

        base_name : str
            Generic name assigned to clarify each output files name.

        in_dir : str, optional
            Input directory to read PyContact files from. Default is current directory.

        out_dir : str, optional
            Output directory to write cleaned PyContact files to. Directory created if does not exist. Default is current directory.

        multiple_files : bool, optional
            Choose True if you have multiple PyContact files (of the same system!) that need to be merged. Default is False.

        Returns
        -------
        NAME : TYPE
            DESCRIPTION.

        """
        if out_dir != "":
            if os.path.exists(out_dir) == False:
                os.makedirs(out_dir)

            if out_dir[-1] != "/":
                out_dir += "/"

        if (in_dir != "") and (in_dir[-1] != "/"):
            in_dir += "/"

        self.base_name = base_name
        self.in_dir = in_dir
        self.out_dir = out_dir

        # Run first pass to clean and rewrite the output.
        if multiple_files == False:
            self._reformat_pycontact_file(pycontact_files)
            df = self._load_pycontact_dataset(pycontact_files)
            df = self._standardize_interaction_names(df)

        # if multiple files to be merged.
        else:
            [self._reformat_pycontact_file(i) for i in pycontact_files]
            dfs = [self._load_pycontact_dataset(i) for i in pycontact_files]
            df = self._merge_pycontact_datasets(dfs)
            df = self._standardize_interaction_names(df)

        return df

    def _reformat_pycontact_file(self, input_file):
        """Take a single PyContact generated input file and reformats so it can be easily read in to Pandas."""
        # TODO - REFACTOR code to instead read this into a df and not save an intermediate, not needed.
        file_in_path = self.in_dir + input_file
        file_out_path = self.out_dir + "Cleaned_" + input_file
        with open(file_in_path, 'r') as file_in:
            filedata = file_in.read()

            filedata = filedata.replace("[", ",").replace("]", ",")
            filedata = re.sub(' +', ' ', filedata)

            # Add a comma after each interaction term so it seperates after them, also rename "other" to "vdw"
            filedata = filedata.replace("hbond", "hbond,").replace(
                "hydrophobic", "hydrophobic,").replace("other", "vdW,").replace("saltbr", "saltbr,")

            with open(file_out_path, 'w') as file_out:
                file_out.write(filedata)

        return print(f"Reformatted PyContact file written to: {file_out_path}")

    def _load_pycontact_dataset(self, input_file):
        """Takes a "Cleaned" PyContact dataset and loads it into a pandas dataframe."""
        file_in_path = self.out_dir + "Cleaned_" + input_file

        df = pd.read_csv(file_in_path, skiprows=1, header=None).T
        df.columns = df.iloc[0]
        df = df.drop([0, 1])
        df = df.reset_index(drop=True)
        # Remove bottom half of the rows which are Hbond occupanicies.
        drop_me = int(len(df)/2 + 1)
        df = df.drop(df.tail(drop_me).index)
        return df

    def _merge_pycontact_datasets(self, dfs):
        """Function to merge multiple PyContact dfs. dfs merged in the same order as they are given."""
        merged_df = pd.concat(dfs, ignore_index='True', sort='False')
        return merged_df.fillna(0.0)

    def _standardize_interaction_names(self, df):
        """Reformat the PyContact generated interaction labels names for easier handling."""
        df = df.rename(columns=lambda x: re.sub(" +", " ", x))
        df = df.rename(columns=lambda x: x.lstrip())
        # Rename column names to add 1 to each Res number
        df_cols = pd.DataFrame(list(df.columns), columns=["Original_Names"])
        # Split current names
        df_cols["Val_1"] = df_cols["Original_Names"].str.split("-").str.get(0)
        df_cols["Val_2"] = df_cols["Original_Names"].str.split("-").str.get(1)
        df_cols["Int_type"] = df_cols["Val_2"].str.split("\d+").str.get(1)

        # Extract the raw parts.
        df_cols["Res1_name"] = df_cols["Val_1"].str.split("\d+").str.get(0)
        df_cols["Res2_name"] = df_cols["Val_2"].str.split("\d+").str.get(0)
        df_cols["Res1_num"] = df_cols["Val_1"].str.split(
            "[a-zA-Z]+").str.get(1)
        df_cols["Res2_num"] = df_cols["Val_2"].str.split(
            "[a-zA-Z]+").str.get(1)

        # Join split out data back together in new column with new format.
        df_cols["New_Names"] = (df_cols["Res1_name"] + df_cols["Res1_num"] +
                                df_cols["Res2_name"] + df_cols["Res2_num"] +
                                df_cols["Int_type"]
                                )
        # Update columns on original DataFrame to transformed names
        df.columns = list(df_cols["New_Names"])
        return df


def main():
    pass


if __name__ == main:
    main()
