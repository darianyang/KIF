"""
This scripts generates a PyMOL script to visualise the results geenrated from a 
WISP calculation performed with Bio3D (generated with R). 

Bio3D can already make a VMD compatible visulisation file with the following command:
"vmd.cnapath()"

"""
import re
from typing import Tuple

# 3 Adjustable arguments below - UPDATE THESE. 

# Inputs.
vmd_file = "WISP_Results/PathGlu200Site.vmd"
paths_file = "WISP_Results/PathGlu200Site_all_paths.txt"

# Output. 
out_file = "WISP_Results/PathGlu200Site_pymol.py"


def parse_vmd_file(vmd_file: str) -> list:
    """
    Parse through the vmd file to obtain a list of the residues on the paths.

    Parameters
    ----------
    vmd_file : str
        File path to the .vmd file generated by Bio3D's suboptimal paths analysis.

    Returns
    ----------
    list
        List of all residues that are on any of the suboptimal paths.
    """
    mol_selections = []
    with open(vmd_file, "r") as f:
        for line in f:
            if "mol selection " in line:
                mol_selections.append(line)

    return [int(s) for s in mol_selections[2].split() if s.isdigit()]


def parse_all_paths_file(paths_file: str) -> Tuple[list, list]:
    """
    Parse the file which contains all the paths found.
    Returns the paths in two different forms.

    Parameters
    ----------
    paths_file : str
        File path to the file generated by Bio3D's suboptimal paths analysis
        which contains lists of all the paths identified.

    Returns
    ----------
    all_paths_concat : list
        Concanated list of all supoptimal paths.
        (Allows for a very simple calculation of how frequently used each residue is).

    all_paths : list
        List of lists, each list being a single path from source to sink.
    """
    all_paths_concat = []
    all_paths = []
    with open(paths_file, "r") as f:
        for line in f:
            split_line = line.split()

            path = []
            for member in split_line:
                try:
                    path.append(int(member))
                except ValueError:
                    pass  # non path members caught.

            if len(path) != 0:
                all_paths_concat.extend(path)
                all_paths.append(path)

    return all_paths_concat, all_paths


def prep_res_counts(all_paths_concat: list) -> dict:
    """
    Determine as a fraction how often each residue show up in all the paths.

    Parameters
    ----------
    all_paths_concat : list
        Concanated list of all supoptimal paths.

    Returns
    ----------
    dict
        Keys are residue numbers, values are fraction of occurence
        accross all paths (i.e. max value = 1).
    """

    # Generate a dict of each residue and its frequenecy of occurence.
    res_counts = dict((x, all_paths_concat.count(x))
                      for x in set(all_paths_concat))
    # scale items in dict so max value = 1
    max_val = max(res_counts.values())
    res_counts.update((k, round(v / max_val, 4))
                      for k, v in res_counts.items())

    return res_counts


def prep_res_res_connections(all_paths: list) -> dict:
    """
    Take all the paths found and determine all residue-residue connections
    and how frequently they occur in each network.

    Parameters
    ----------
    all_paths: list
        List of lists, each list being a single path from source to sink.

    Returns
    ----------
    dict
        Keys are residue-residue pairs and values are their normalised frequency.
        Max frequency value is 0.5 (good for pymol).
    """
    interacting_pairs = {}
    for path in all_paths:
        for res1, res2 in zip(path, path[1:]):
            # catch both possible res number orderings..
            pair_v1 = str(res1) + " " + str(res2)
            pair_v2 = str(res2) + " " + str(res1)

            if pair_v1 in interacting_pairs:
                interacting_pairs[pair_v1] += 1

            elif pair_v2 in interacting_pairs:
                # except happens if pair_v2 occurs before pair_v1 in list.
                try:
                    interacting_pairs[pair_v1] += 1
                except KeyError:
                    interacting_pairs[pair_v1] = 1

            else:
                interacting_pairs[pair_v1] = 1

    # scale items in dict so max value = 0.5
    max_interactions = max(interacting_pairs.values())
    interacting_pairs.update((k, round(v / (max_interactions*2), 4))
                             for k, v in interacting_pairs.items())

    return interacting_pairs


def main():
    """Runs everything"""

    path_residues = parse_vmd_file(vmd_file=vmd_file)
    all_paths_concat, all_paths = parse_all_paths_file(paths_file=paths_file)
    interacting_pairs = prep_res_res_connections(all_paths=all_paths)
    res_counts = prep_res_counts(all_paths_concat=all_paths_concat)

    # Write the pymol file.
    pymol_out_text = ""
    pymol_out_text += "# To run this script you will need to get a copy of 'draw_links.py' from the internet.\n"
    pymol_out_text += "# You can find it freely available here: \n"
    pymol_out_text += "# http://pldserver1.biochem.queensu.ca/~rlc/work/pymol/draw_links.py \n"
    pymol_out_text += "# Place the 'draw_links.py' file in your working directory. \n"
    pymol_out_text += "run draw_links.py\n"

    # sticks for all path residues
    pymol_out_text += "sele path_residues, resi "
    for residue in path_residues:
        pymol_out_text += f"{residue}+"
    pymol_out_text += " \n"
    pymol_out_text += "show sticks, path_residues \n"

    # spheres for all network residues, with sizes scaled by frequency.
    for res_numb, sphere_size in res_counts.items():
        pymol_out_text += f"show spheres, resi {res_numb} and name CA\n"
        pymol_out_text += f"set sphere_scale, {sphere_size:.4f}, resi {res_numb} and name CA\n"

    for res_combo, cylider_size in interacting_pairs.items():
        residues = res_combo.split()

        pymol_out_text += (f"draw_links selection1=resi {residues[0]}, " +
                           f"selection2=resi {residues[1]}, " +
                           "color=grey, " +
                           f"radius={cylider_size} \n"
                           )
    pymol_out_text += "group Paths, link*"

    # Finally save.
    with open(out_file, "w+") as file_out:
        file_out.write(pymol_out_text)


if __name__ == "__main__":
    main()
