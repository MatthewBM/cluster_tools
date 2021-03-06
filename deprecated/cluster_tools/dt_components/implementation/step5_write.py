#! /usr/bin/python

import os
import json
import argparse
import z5py
import numpy as np
import nifty


def write_block(ds, blocking, block_id, node_labels, offsets):
    off = offsets[block_id]
    block = blocking.getBlock(block_id)
    bb = tuple(slice(beg, end) for beg, end in zip(block.begin, block.end))
    seg = ds[bb]
    mask = seg != 0
    seg[mask] += off
    seg = nifty.tools.take(node_labels, seg)
    ds[bb] = seg


def step5_write_blocks(path, out_key, cache_folder, job_id):

    assignment_path = os.path.join(cache_folder, 'node_assignments.npy')
    node_labels = np.load(assignment_path)

    offsets_path = os.path.join(cache_folder, 'block_offsets.json')
    with open(offsets_path) as f:
        offset_config = json.load(f)
        offsets = offset_config['offsets']
        empty_blocks = offset_config['empty_blocks']

    input_file = os.path.join(cache_folder, '1_config_%i.json' % job_id)
    with open(input_file) as f:
        input_config = json.load(f)
        block_shape = input_config['block_shape']
        block_ids = list(input_config['block_config'].keys())
        # json keys are always str, so we need to cast to int
        block_ids = list(map(int, block_ids))

    shape = z5py.File(path)[out_key].shape
    blocking = nifty.tools.blocking(roiBegin=[0, 0, 0],
                                    roiEnd=list(shape),
                                    blockShape=list(block_shape))

    f = z5py.File(path)
    ds = f[out_key]

    [write_block(ds, blocking, block_id, node_labels, offsets)
     for block_id in block_ids if block_id not in empty_blocks]

    print("Success")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=str)
    parser.add_argument('out_key', type=str)
    parser.add_argument('cache_folder', type=str)
    parser.add_argument('job_id', type=int)

    args = parser.parse_args()
    step5_write_blocks(args.path, args.out_key,
                       args.cache_folder, args.job_id)
