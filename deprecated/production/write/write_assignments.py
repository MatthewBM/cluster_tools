#! /usr/bin/python

import time
import os
import json
import argparse
import subprocess
import pickle
from concurrent import futures

import numpy as np
import luigi
import z5py
import nifty


# TODO more clean up (job config files)
# TODO computation with rois
class WriteAssignmentTask(luigi.Task):
    """
    Write node assignments for all blocks
    """

    path = luigi.Parameter()
    in_key = luigi.Parameter()
    out_key = luigi.Parameter()
    config_path = luigi.Parameter()
    # maximal number of jobs that will be run in parallel
    max_jobs = luigi.IntParameter()
    tmp_folder = luigi.Parameter()
    # identifier to seperate the output files of different write
    # assignment tasks
    identifier = luigi.Parameter()
    # TODO would be more elegant to express both as tasks,
    # but for this we would need an empty default task
    # for the offsets
    dependency = luigi.TaskParameter()
    offset_path = luigi.Parameter(default='')
    # FIXME default does not work; this still needs to be specified
    time_estimate = luigi.IntParameter(default=10)
    run_local = luigi.BoolParameter(default=False)

    def requires(self):
        return self.dependency

    def _prepare_jobs(self, n_jobs, block_list, block_shape, n_threads):
        for job_id in range(n_jobs):
            block_jobs = block_list[job_id::n_jobs]
            job_config = {'block_shape': block_shape,
                          'block_list': block_jobs,
                          'n_threads': n_threads}
            config_path = os.path.join(self.tmp_folder, 'write_assignments_config_job%i.json' % job_id)
            with open(config_path, 'w') as f:
                json.dump(job_config, f)

    def _submit_job(self, job_id, assignment_path, n_threads):
        script_path = os.path.join(self.tmp_folder, 'write_assignments.py')
        config_path = os.path.join(self.tmp_folder, 'write_assignments_config_job%i.json' % job_id)
        if self.offset_path == '':
            command = '%s %s %s %s %s %s %s %i' % (script_path, self.path, self.in_key, self.out_key,
                                                   config_path, assignment_path, self.tmp_folder, job_id)
        else:
            command = '%s %s %s %s %s %s %s %i --offset_path %s' % (script_path, self.path,
                                                                    self.in_key, self.out_key,
                                                                    config_path, assignment_path,
                                                                    self.tmp_folder, job_id,
                                                                    self.offset_path)
        log_file = os.path.join(self.tmp_folder, 'logs', 'log_write_assignments_%i' % job_id)
        err_file = os.path.join(self.tmp_folder, 'error_logs', 'err_write_assignments_%i.err' % job_id)
        bsub_command = 'bsub -n %i -J write_assignments_%i -We %i -o %s -e %s \'%s\'' % (n_threads,
                                                                                         job_id,
                                                                                         self.time_estimate,
                                                                                         log_file,
                                                                                         err_file,
                                                                                         command)
        if self.run_local:
            subprocess.call([command], shell=True)
        else:
            subprocess.call([bsub_command], shell=True)

    def _collect_outputs(self, n_jobs):
        times = []
        processed_blocks = []
        for job_id in range(n_jobs):
            res_file = os.path.join(self.tmp_folder, 'write_assignments_job%i.json' % job_id)
            try:
                with open(res_file) as f:
                    res = json.load(f)
                processed_blocks.extend(list(map(int, res.keys())))
                times.extend(list(res.values()))
                os.remove(res_file)
            except Exception:
                continue
        return processed_blocks, times

    def run(self):
        from .. import util

        # copy the script to the temp folder and replace the shebang
        file_dir = os.path.dirname(os.path.abspath(__file__))
        util.copy_and_replace(os.path.join(file_dir, 'write_assignments.py'),
                              os.path.join(self.tmp_folder, 'write_assignments.py'))

        with open(self.config_path) as f:
            config = json.load(f)
            block_shape = config['block_shape']
            chunks = config['chunks']
            n_threads = config['n_threads']
            roi = config.get('roi', None)

        # make the output dataset
        f5 = z5py.File(self.path)
        shape = f5[self.in_key].shape
        f5.require_dataset(self.out_key, shape=shape,
                           chunks=tuple(chunks), dtype='uint64', compression='gzip')

        blocking = nifty.tools.blocking([0, 0, 0], list(shape), block_shape)
        if roi is None:
            n_blocks = blocking.numberOfBlocks
            block_list = list(range(n_blocks))
        else:
            block_list = blocking.getBlockIdsOverlappingBoundingBox(roi[0],
                                                                    roi[1],
                                                                    [0, 0, 0]).tolist()
            n_blocks = len(block_list)

        # find the actual number of jobs and prepare job configs
        n_jobs = min(n_blocks, self.max_jobs)
        self._prepare_jobs(n_jobs, block_list, block_shape, n_threads)

        # get the block offset path from out dependency
        assignment_path = self.input().path

        # submit the jobs
        if self.run_local:
            # this only works in python 3 ?!
            with futures.ProcessPoolExecutor(n_jobs) as tp:
                tasks = [tp.submit(self._submit_job, job_id, assignment_path, n_threads)
                         for job_id in range(n_jobs)]
                [t.result() for t in tasks]
            # for job_id in range(n_jobs):
            #     self._submit_job(job_id, assignment_path, n_threads)
        else:
            for job_id in range(n_jobs):
                self._submit_job(job_id, assignment_path, n_threads)

        # wait till all jobs are finished
        if not self.run_local:
            util.wait_for_jobs('papec')

        # check the job outputs
        processed_blocks, times = self._collect_outputs(n_jobs)
        assert len(processed_blocks) == len(times)
        success = len(processed_blocks) == n_blocks

        # write output file if we succeed, otherwise write partial
        # success to different file and raise exception
        if success:
            out = self.output()
            # TODO does 'out' support with block?
            fres = out.open('w')
            json.dump({'times': times}, fres)
            fres.close()
        else:
            log_path = os.path.join(self.tmp_folder, 'write_assignments_partial.json')
            with open(log_path, 'w') as out:
                json.dump({'times': times,
                           'processed_blocks': processed_blocks}, out)
            raise RuntimeError("WriteAssignmentTask failed, %i / %i blocks processed," % (len(processed_blocks),
                                                                                          n_blocks) +
                               "serialized partial results to %s" % log_path)

    def output(self):
        return luigi.LocalTarget(os.path.join(self.tmp_folder,
                                              'write_assignments_%s.log' % self.identifier))


def write_block_with_offsets(ds_in, ds_out, blocking, block_id, node_labels, offsets):
    t0 = time.time()
    off = offsets[block_id]
    block = blocking.getBlock(block_id)
    bb = tuple(slice(beg, end) for beg, end in zip(block.begin, block.end))
    seg = ds_in[bb]
    mask = seg != 0
    seg[mask] += off
    # choose the appropriate function for array or dictionary
    if isinstance(node_labels, np.ndarray):
        seg = nifty.tools.take(node_labels, seg)
    else:
        seg = nifty.tools.takeDict(node_labels, seg)
    ds_out[bb] = seg
    return time.time() - t0


def write_block(ds_in, ds_out, blocking, block_id, node_labels):
    print("writing block", block_id)
    t0 = time.time()
    block = blocking.getBlock(block_id)
    bb = tuple(slice(beg, end) for beg, end in zip(block.begin, block.end))
    seg = ds_in[bb]
    mask = seg != 0
    # check if this block is empty and don't write if so
    if np.sum(mask) == 0:
        return time.time() - t0
    # choose the appropriate function for array or dictionary
    if isinstance(node_labels, np.ndarray):
        seg = nifty.tools.take(node_labels, seg)
    else:
        # this copys the dict and hence is extremely RAM hungry
        # seg = nifty.tools.takeDict(node_labels, seg)
        this_labels = nifty.tools.unique(seg)
        this_assignment = {label: node_labels[label] for label in this_labels}
        seg = nifty.tools.takeDict(this_assignment, seg)
    ds_out[bb] = seg
    print("done", block_id)
    return time.time() - t0


def write_assignments(path, in_key, out_key,
                      config_path,
                      assignment_path,
                      tmp_folder, job_id,
                      offset_path=''):

    with open(config_path) as f:
        input_config = json.load(f)
        block_shape = input_config['block_shape']
        block_ids = input_config['block_list']
        n_threads = input_config['n_threads']

    print("Loading assignments")
    # load consecutive labeling from npy or n5
    # or dictionary labeling from pkl
    if os.path.isdir(assignment_path):
        assignment_root, assignment_key = os.path.split(assignment_path)
        # we only need to load the second axis, because the nodes
        # are guaranteed to be consecutive
        ds_labels = z5py.File(assignment_root)[assignment_key]
        ds_labels.n_threads = n_threads
        node_labels = ds_labels[:, 1]
    else:
        assert assignment_path.split('.')[-1] == 'pkl'
        with open(assignment_path, 'rb') as f:
            node_labels = pickle.load(f)
        assert isinstance(node_labels, dict)
    print("done")

    with_offsets = offset_path != ''
    if with_offsets:
        with open(offset_path) as f:
            offset_config = json.load(f)
            offsets = offset_config['offsets']
            empty_blocks = offset_config['empty_blocks']

    f = z5py.File(path)
    ds_in = f[in_key]
    ds_out = f[out_key]
    shape = ds_in.shape
    blocking = nifty.tools.blocking(roiBegin=[0, 0, 0],
                                    roiEnd=list(shape),
                                    blockShape=list(block_shape))

    # write all the blocks
    times = []

    if with_offsets:
        with futures.ThreadPoolExecutor(n_threads) as tp:
            tasks = [tp.submit(write_block_with_offsets, ds_in, ds_out,
                               blocking, block_id, node_labels, offsets)
                     for block_id in block_ids if block_id not in empty_blocks]
            times = [t.result() for t in tasks]
    else:
        with futures.ThreadPoolExecutor(n_threads) as tp:
            tasks = [tp.submit(write_block, ds_in, ds_out,
                               blocking, block_id, node_labels) for block_id in block_ids]
            times = [t.result() for t in tasks]

    # write the max-id with job 0
    if job_id == 0:
        if isinstance(node_labels, dict):
            max_id = np.max(list(node_labels.values()))
        else:
            max_id = node_labels.max()
        ds_out.attrs['maxId'] = int(max_id)

    save_path = os.path.join(tmp_folder, 'write_assignments_job%i.json' % job_id)
    with open(save_path, 'w') as f:
        json.dump({block_id: tt for block_id, tt in zip(block_ids, times)}, f)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=str)
    parser.add_argument('in_key', type=str)
    parser.add_argument('out_key', type=str)
    parser.add_argument('config_path', type=str)
    parser.add_argument('assignment_path', type=str)
    parser.add_argument('tmp_folder', type=str)
    parser.add_argument('job_id', type=int)
    parser.add_argument('--offset_path', type=str, default='')

    args = parser.parse_args()
    write_assignments(args.path, args.in_key, args.out_key,
                      args.config_path,
                      args.assignment_path, args.tmp_folder,
                      args.job_id, args.offset_path)
