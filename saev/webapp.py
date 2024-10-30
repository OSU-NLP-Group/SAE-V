import os
import pickle
import typing

import beartype
import datasets
import torch
import tqdm
from PIL import Image

from . import config


@beartype.beartype
def safe_load(path: str) -> object:
    return torch.load(path, map_location="cpu", weights_only=True)


@beartype.beartype
def make_img_grid(imgs: list):
    # Resize to 224x224
    img_width, img_height = 224, 224
    imgs = [img.resize((img_width, img_height)).convert("RGB") for img in imgs]

    # Create an image grid
    grid_size = 4
    border_size = 2  # White border thickness

    # Create a new image with white background
    grid_width = grid_size * img_width + (grid_size - 1) * border_size
    grid_height = grid_size * img_height + (grid_size - 1) * border_size
    img_grid = Image.new("RGB", (grid_width, grid_height), "white")

    # Paste images in the grid
    x_offset, y_offset = 0, 0
    for i, img in enumerate(imgs):
        img_grid.paste(img, (x_offset, y_offset))
        x_offset += img_width + border_size
        if (i + 1) % grid_size == 0:
            x_offset = 0
            y_offset += img_height + border_size
    return img_grid


@beartype.beartype
def main(cfg: config.Config, load_from: str, dump_to: str):
    """
    Args:
        cfg: Experimental config.
        load_from: Where to load the results of analysis.py from.
        dump_to: Where to write the results.
    """
    # (d_sae,)
    sparsity = safe_load(f"{load_from}/sae_sparsity.pt")

    # (d_sae, k)
    top_indices = safe_load(f"{load_from}/max_activating_image_indices.pt")

    # (d_sae, k)
    top_values = safe_load(f"{load_from}/max_activating_image_values.pt")

    # (d_sae, k)
    # top_label_indices = safe_load(f"{load_from}/max_activating_image_label_indices.pt")

    sae_mean_acts = top_values.mean(dim=-1)
    if isinstance(cfg.data, config.TreeOfLife):
        import wids

        dataset = wids.ShardListDataset(cfg.data.metadata).add_transform(
            lambda sample: {"image": sample[".jpg"]}
        )
    elif isinstance(cfg.data, config.Imagenet):
        dataset = datasets.load_dataset(cfg.data.name, split="train")
    else:
        typing.assert_never(cfg.data)

    n_neurons, _ = top_values.shape
    entropies = torch.zeros(n_neurons)

    # for i in range(n_neurons):
    #     # Get unique labels and their indices for the current sample
    #     unique_labels, _ = top_label_indices[i].unique(return_inverse=True)
    #     # ignore label 949 = dataset[0]['label'] - the default label index
    #     unique_labels = unique_labels[unique_labels != 949]
    #     if len(unique_labels) == 0:
    #         entropies[i] = -1
    #         continue

    #     count = 0
    #     for label in unique_labels:
    #         count += (top_label_indices[i] == label).sum()

    #     if count < 10:
    #         entropies[i] = -1  # discount as too few datapoints!
    #         continue

    #     # Sum probabilities based on these labels
    #     summed_probs = torch.zeros_like(unique_labels, dtype=top_values.dtype)
    #     for j, label in enumerate(unique_labels):
    #         summed_probs[j] = top_values[i][top_label_indices[i] == label].sum().item()
    #     # Calculate entropy for the summed probabilities
    #     # Normalize to make it a valid probability distribution
    #     summed_probs = summed_probs / summed_probs.sum()
    #     # small epsilon to avoid log(0)
    #     entropy = -torch.sum(summed_probs * torch.log(summed_probs + 1e-9))
    #     entropies[i] = entropy

    # Mask all neurons in the dense cluster
    mask = (
        (torch.log10(sparsity) > -4) & (torch.log10(sae_mean_acts) > -0.7)
        # & (entropies > -1)
    )
    indices = torch.tensor([i for i in range(n_neurons)])
    indices = list(indices[mask])

    os.makedirs(f"{dump_to}/neurons", exist_ok=True)
    torch.save(entropies, f"{dump_to}/neurons/entropy.pt")
    for i in tqdm.tqdm(indices, desc="saving highest activating grids"):
        i = int(i.item())
        neuron_dir = f"{dump_to}/neurons/{i}"
        os.makedirs(neuron_dir, exist_ok=True)

        # Image grid
        imgs = [dataset[int(img_i)]["image"] for img_i in top_indices[i][:16]]
        img_grid = make_img_grid(imgs)
        img_grid.save(f"{neuron_dir}/highest_activating_images.png")

        # Metadata
        metadata = {
            "neuron index": i,
            "log 10 sparsity": torch.log10(sparsity)[i].item(),
            "mean activation": sae_mean_acts[i].item(),
            "label entropy": entropies[i].item(),
        }
        with open(f"{neuron_dir}/metadata.pkl", "wb") as pickle_file:
            pickle.dump(metadata, pickle_file)
