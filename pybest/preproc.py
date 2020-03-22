import numpy as np
import nibabel as nib
import pandas as pd
from tqdm import tqdm
from nilearn import image, masking, signal
from scipy.signal import savgol_filter
from nistats.design_matrix import _cosine_drift as dct_set
from sklearn.decomposition import PCA
from .utils import _load_gifti, tqdm_out


def preprocess_func(funcs, mask, space, high_pass_type, high_pass,
                    savgol_order, gm_thresh, tr, logger):
    """ Preprocesses a set of functional files (either volumetric nifti or
    surface gifti); high-pass filter (DCT) and normalization only.

    Parameters
    ----------
    funcs : list
        List of paths to functional files
    mask : str
        Path to mask (for now: assume it's a GM probseg file)
    space : str
        Name of space ('T1w', 'fsaverage{5,6}', 'MNI152NLin2009cAsym')
    logger : logging object
        Main logger (from cli.py)
    high_pass_type : str
        Either 'dct' or 'savgol'
    high_pass : float
        High-pass cutoff (in Hz)
    savgol_order : int
        Savitsky-Golay polyorder (default: 4)
    gm_thresh : float
        Gray matter probability threshold (higher = included in binary mask)
    tr : float
        TR of scan (only relevant if space is fsaverage) in seconds

    Returns
    -------
    data_ : np.ndarray
        2D array (time x voxels) with run-wise concatenated data
    run_idx_ : np.ndarray
        1D array with run indices, [0, 0, 0, ... , 1, 1, 1, ... , R, R, R]
        for R runs
    """

    if 'fs' not in space:  # no need for mask in surface files
        if mask is None:  # use functional brain masks
            logger.info("Creating mask by intersection of function masks")
            fmasks = [f.replace('desc-preproc_bold', 'desc-brain_mask') for f in funcs]
            mask = masking.intersect_masks(fmasks, threshold=0.8)
        else:
            # Using provided masks
            logger.info("Creating mask using GM probability map")

            # Downsample (necessary by default)
            mask = image.resample_to_img(mask, funcs[0])
            mask_data = mask.get_fdata()

            # Threshold
            mask_data = (mask_data >= gm_thresh).astype(int)
            mask = nib.Nifti1Image(mask_data, affine=mask.affine)
    else:
        # If fsaverage{5,6} space, don't use any mask
        mask = None

    logger.info("Starting preprocessing of functional data ... ")

    data_, run_idx_ = [], []
    for i, func in enumerate(tqdm(funcs, file=tqdm_out)):

        # Load data
        if 'fs' in space:  # assume gifti
            data = _load_gifti(func)
        else:
            # Mask data and extract stuff
            data = masking.apply_mask(func, mask)

        # By now, data is a 2D array (time x voxels)
        n_vol = data.shape[0]
        data = hp_filter(data, tr, n_vol, high_pass_type, high_pass, savgol_order)
        data_.append(data)

        # Add to run index
        run_idx_.append(np.ones(n_vol) * i)

    # Concatenate data in time dimension (or should we keep it in lists?)
    data_ = np.vstack(data_)
    run_idx_ = np.concatenate(run_idx_)

    logger.info(
        f"HP-filtered/normalized func data has {data_.shape[0]} timepoints "
        f"(across {len(funcs)} runs) and {data_.shape[1]} voxels"
    )

    return data_, run_idx_


def preprocess_conf(confs, ricors, high_pass_type, high_pass, savgol_order, tr, logger):
    """ Preprocesses confounds by doing the following:
    1. Horizontal concatenation of Fmriprep confounds and RETROICOR (if any)
    2. Set NaNs to 0
    3. High-pass the data (same as functional data)
    4. PCA

    Parameters
    ----------

    Returns
    -------

    """
    
    logger.info("Starting preprocessing of confounds")
    data_ = []
    for i, conf in enumerate(confs):

        data = pd.read_csv(conf, sep='\t')
        to_remove = [col for col in data.columns if 'cosine' in col]
        data = data.drop(to_remove, axis=1)

        if ricors is not None:
            ricor_data = pd.read_csv(ricors[i], sep='\t')
            data = pd.concat((data, ricor_data), axis=1)
        
        logger.info(f"Loaded {data.shape[1]} confound variables for run {i+1}")
        data = data.fillna(0)
        n_vol = data.shape[0]
        data.iloc[:, :] = hp_filter(data.to_numpy(), tr, n_vol, high_pass_type, high_pass, savgol_order)
        data_.append(data)

    data_ = pd.concat(data_, axis=0, join='inner', ignore_index=True)

    pca = PCA()
    data_decomp = pca.fit_transform(data_)
    n_comp_for_90r2 = np.argmax(np.cumsum(pca.explained_variance_ratio_) > 0.9)
    logger.info(f"PCA needed {n_comp_for_90r2} components to explain 90% of the variance")

    logger.info(
        f"HP-filtered/normalized confound data has {data_.shape[0]} timepoints "
        f"(across {len(confs)} runs) and {data_.shape[1]} common variables"
    )

    return 


def hp_filter(data, tr, n_vol, high_pass_type, high_pass, savgol_order):
    frame_times = np.linspace(0.5 * tr, n_vol * (tr + 0.5), n_vol, endpoint=False)    

    # Create high-pass filter and clean
    if high_pass_type == 'dct':
        hp_set = dct_set(high_pass, frame_times)[:, :-1]  # remove intercept
        data = signal.clean(data, detrend=True, standardize='zscore', confounds=hp_set)
    else:  # savgol, hardcode polyorder
        window = int(np.round((1/high_pass) / tr))
        hp_sig = savgol_filter(data, window_length=window, polyorder=4, axis=0)
        data -= hp_sig
        data = (data - data.mean(axis=0)) / data.std(axis=0)
    
    return data


def save_preproc_data(sub, ses, task, funcs, confs, events, mask, work_dir):
    pass


def load_preproc_data(sub, ses, task, work_dir):
    pass