#! /usr/bin/python

import json
import os
import argparse
import numpy as np

import z5py
import nifty


def blocks_to_jobs(shape, block_shape, n_jobs, tmp_folder, output_prefix):
    blocking = nifty.tools.blocking(roiBegin=[0, 0, 0],
                                    roiEnd=list(shape),
                                    blockShape=block_shape)
    n_blocks = blocking.numberOfBlocks
    assert n_jobs <= n_blocks, "%i, %i" % (n_jobs, n_blocks)

    block_list = list(range(n_blocks))
    for job_id in range(n_jobs):
        np.save(os.path.join(tmp_folder, '%s_%i.npy' % (output_prefix, job_id)),
                block_list[job_id::n_jobs])
    return n_blocks


def edges_to_jobs2(n_edges, chunk_size, n_jobs, tmp_folder, n_blocks):
    n_chunks = n_edges // chunk_size + 1 if chunk_size % n_edges != 0 else n_edges // chunk_size
    if n_jobs > n_chunks:
        n_jobs = n_chunks

    # distribute chunks to jobs as equal as possible
    chunks_per_job = np.zeros(n_jobs, dtype='uint32')
    chunk_count = n_chunks
    job_id = 0
    while chunk_count > 0:
        chunks_per_job[job_id] += 1
        chunk_count -= 1
        job_id += 1
        job_id = job_id % n_jobs
    assert np.sum(chunks_per_job) == n_chunks

    chunk_index = 0
    for job_id in range(n_jobs):
        print(chunk_index, chunks_per_job[job_id])
        edge_begin = chunk_index * chunk_size
        edge_end = (chunk_index + chunks_per_job[job_id]) * chunk_size
        chunk_index += chunks_per_job[job_id]
        if job_id == n_jobs - 1:
            edge_end = n_edges
        print(job_id, edge_begin, edge_end)
        np.save(os.path.join(tmp_folder, "2_input_%i.npy" % job_id),
                np.array([edge_begin, edge_end, n_blocks], dtype='uint32'))


def make_default_offsets(tmp_folder):
    offset_file = os.path.join(tmp_folder, 'offsets.json')
    default_offsets = [[-1, 0, 0], [0, -1, 0], [0, 0, -1],
                       [-2, 0, 0], [0, -3, 0], [0, 0, -3],
                       [-3, 0, 0], [0, -9, 0], [0, 0, -9],
                       [-4, 0, 0], [0, -27, 0], [0, 0, -27]]
    with open(offset_file, 'w') as f:
        json.dump(default_offsets, f)


def make_nearest_offsets(tmp_folder):
    offset_file = os.path.join(tmp_folder, 'offsets.json')
    default_offsets = [[-1, 0, 0], [0, -1, 0], [0, 0, -1]]
    with open(offset_file, 'w') as f:
        json.dump(default_offsets, f)


def prepare(graph_path, graph_key, out_path, out_key, block_shape,
            n_jobs1, n_jobs2, tmp_folder):
    assert os.path.exists(graph_path), graph_path
    f_graph = z5py.File(graph_path, use_zarr_format=False)
    shape = f_graph.attrs['shape']
    ds_graph = f_graph[graph_key]
    n_edges = ds_graph.attrs['numberOfEdges']

    f = z5py.File(out_path, use_zarr_format=False)
    if 'blocks' not in f:
        f.create_group('blocks')

    # chunk size = 64**3
    chunk_size = min(262144, n_edges)

    if not os.path.exists(tmp_folder):
        os.mkdir(tmp_folder)

    make_default_offsets(tmp_folder)
    # make_nearest_offsets(tmp_folder)

    if out_key in f:
        ds = f[out_key]
        assert ds.shape == (n_edges, 10)
        assert ds.chunks == (chunk_size, 1)
    else:
        f.create_dataset(out_key, dtype='float64', shape=(n_edges, 10),
                         chunks=(chunk_size, 1), compression='gzip')

    n_blocks = blocks_to_jobs(shape, block_shape, n_jobs1, tmp_folder, "1_input")

    edges_to_jobs2(n_edges, chunk_size, n_jobs2, tmp_folder, n_blocks)
    print("Success")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("graph_path", type=str)
    parser.add_argument("graph_key", type=str)
    parser.add_argument("out_path", type=str)
    parser.add_argument("out_key", type=str)
    parser.add_argument("--block_shape", nargs=3, type=int)
    parser.add_argument("--n_jobs1", type=int)
    parser.add_argument("--n_jobs2", type=int)
    parser.add_argument("--tmp_folder", type=str)
    args = parser.parse_args()

    prepare(args.graph_path, args.graph_key,
            args.out_path, args.out_key,
            list(args.block_shape), args.n_jobs1,
            args.n_jobs2, args.tmp_folder)
