import os
import numpy as np

# Parameters
output_file = "band_gaps_eigenval.txt"
folders = [f"{i:03d}" for i in range(1, 501)]  # Folder names from 001 to 500
band_gaps = []  # List to store valid band gaps

def extract_band_gap_from_eigenval(eigenval_file):
    """
    Extracts the band gap from an EIGENVAL file by identifying the VBM and CBM energies.
    """
    vbm_energy = None
    cbm_energy = None

    with open(eigenval_file, "r") as file:
        for line in file:
            parts = line.split()
            if len(parts) == 3:  # Ensure the line has 3 columns: index, energy, occupation
                energy = float(parts[1])
                occupation = float(parts[2])

                # Identify VBM (last 1.000000 occupation)
                if occupation == 1.000:
                    vbm_energy = energy

                # Identify CBM (first 0.000000 occupation after VBM)
                if occupation == 0.000 and vbm_energy is not None:
                    cbm_energy = energy
                    break  # Stop after finding the CBM

    # Ensure both VBM and CBM are found
    if vbm_energy is None or cbm_energy is None:
        raise ValueError("Could not identify VBM or CBM in EIGENVAL.")

    return cbm_energy - vbm_energy  # Band gap

# Open the output file
with open(output_file, "w") as f:
    f.write("Folder\tBand Gap (eV)\n")
    f.write("====================\n")

    # Loop through each folder
    for folder in folders:
        eigenval_path = os.path.join(folder, "EIGENVAL")

        # Check if EIGENVAL exists
        if os.path.exists(eigenval_path):
            try:
                # Extract band gap from EIGENVAL
                band_gap = extract_band_gap_from_eigenval(eigenval_path)

                # Save band gap to list and write to file
                band_gaps.append(band_gap)
                f.write(f"{folder}\t{band_gap:.2f}\n")
                print(f"Folder {folder}: Band Gap = {band_gap:.2f} eV")
            except ValueError as e:
                # Handle missing VBM/CBM
                f.write(f"{folder}\tError: {e}\n")
                print(f"Folder {folder}: Error - {e}")
            except Exception as e:
                # Handle other parsing errors
                f.write(f"{folder}\tError: {e}\n")
                print(f"Folder {folder}: Error - {e}")
        else:
            # Handle missing EIGENVAL files
            f.write(f"{folder}\tError: EIGENVAL not found\n")
            print(f"Folder {folder}: EIGENVAL not found")

    # Calculate statistics if valid band gaps exist
    if band_gaps:
        mean_band_gap = np.mean(band_gaps)
        std_band_gap = np.std(band_gaps)

        # Write statistics to the file
        f.write("\n====================\n")
        f.write(f"Average Band Gap: {mean_band_gap:.2f} eV\n")
        f.write(f"Standard Deviation: {std_band_gap:.2f} eV\n")
        print(f"\nAverage Band Gap: {mean_band_gap:.2f} eV")
        print(f"Standard Deviation: {std_band_gap:.2f} eV")
    else:
        f.write("\nNo valid band gaps found.\n")
        print("\nNo valid band gaps found.")


