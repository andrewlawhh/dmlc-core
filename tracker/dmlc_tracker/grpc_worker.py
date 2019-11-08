'''
Script run by worker machines to start listening for RPCs.
gRPC Worker API

usage - python3 grpc_worker.py <PORT> <PATH_TO_DATA>

export DMLC_TRACKER_URI='10.100.216.229'; export DMLC_TRACKER_PORT='9091'; export DMLC_ROLE='worker';export DMLC_NODE_HOST='localhost';export DMLC_NUM_WORKER='2';export DMLC_NUM_SERVER='0';python3 ../../../dmlc-core/tracker/dmlc_tracker/grpc_worker.py 50051 ../data/partition_2_train.csv;
'''
from concurrent import futures

import _credentials

import fxgb_pb2
import fxgb_pb2_grpc
import grpc

import ctypes
import multiprocessing
import os
import shlex
import subprocess
import sys

import pandas as pd
import xgboost as xgb


def get_dmlc_vars(env):
    '''
    Returns list of strings representing DMLC variables needed for rabit.
    Parsed in allreduce_base.cc from '<name>=<value>' format.
    
    Param:
        env - Env protobuf
    
    Return:
        list containing new environment variables
    '''
    temp = [
        'DMLC_TRACKER_URI='+env.DMLC_TRACKER_URI,
        'DMLC_TRACKER_PORT='+str(env.DMLC_TRACKER_PORT),
        'DMLC_ROLE='+env.DMLC_ROLE,
        'DMLC_NODE_HOST='+env.DMLC_NODE_HOST,
        'DMLC_NUM_WORKER='+str(env.DMLC_NUM_WORKER),
        'DMLC_NUM_SERVER='+str(env.DMLC_NUM_SERVER),
    ]
    # Python strings are unicode, but C strings are bytes, so we must convert to bytes.
    return [bytes(s, 'utf-8') for s in temp]

class FederatedXGBoostServicer():
    ''' gRPC servicer class which implements worker machine RPCs API. '''
    
    def __init__(self, port, data_path):
        self.model = None
        self.dmlc_vars = None
        self.port = port
        self.data_path = data_path
        print("Started up FXGB worker. Now listening on port %s for RPC to start job." % self.port)

    def StartJob(self, request, context):
        '''
        Runs a script, specified by the aggregator, on this worker machine.
        '''
        print('Request from aggregator to run this job:', request.cmd)
        print('Session password is:', request.password)
        accept_job = input("Run this job? [Y/N]: ")
        while accept_job not in {'Y', 'N'}:
            print("Please enter 'Y' to confirm or 'N' to reject.")
            accept_job = input("Run this job? [Y/N]: ")
        
        if accept_job == 'Y':
            try:
                args = shlex.split(request.cmd) + [self.data_path]
                env = update_env_vars(request.env)
                subprocess.Popen(args, env=env)
                return fxgb_pb2.WorkerResponse(success=True)
            except:
                return fxgb_pb2.WorkerResponse(success=False)
        else:
            return fxgb_pb2.WorkerResponse(success=False)

    def Init(self, request, context):
        '''
        Initializes rabit and environment variables.
        When worker receives this RPC, it can accept or reject the federated training session.

        Params:
            request - InitRequest proto. Contains environment variables
        
        Return:
            WorkerResponse proto (confirmation of initialization success or failure).
        '''
        print('Request from aggregator [%s] to start federated training session:' % context.peer())
        accept_job = None
        while accept_job not in {'Y', 'N'}:
            print("Please enter 'Y' to confirm or 'N' to reject.")
            accept_job = input("Join session? [Y/N]: ")
        if accept_job == 'Y':
            self.dmlc_vars = get_dmlc_vars(request.env)
            return fxgb_pb2.WorkerResponse(success=True)
        else:
            return fxgb_pb2.WorkerResponse(success=False)

    def Train(self, request, context):
        '''
        Starts distributed training.

        Return:
            WorkerResponse proto (confirmation of training success or failure).
        '''
        print('Request from aggregator [%s] to start federated training session:' % context.peer())
        xgb.rabit.init(self.dmlc_vars)
        print('Loading dataset...')
        dataset = pd.read_csv(self.data_path, delimiter=',', header=None)
        data, label = dataset.iloc[:, 1:], dataset.iloc[:, 0]
        dtrain = xgb.DMatrix(data, label=label)
        print('Dataset loaded.')
        param = {}     # doesnt matter?
        num_round = 10 # doesnt matter?
        print('Starting training...')
        model = xgb.train(param, dtrain, num_round)
        print('Training finished.')
        # save model
        xgb.rabit.finalize()


# Start gRPC server listening on port 'port'
def start_worker(port, data_path):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    fxgb_pb2_grpc.add_FXGBWorkerServicer_to_server(FederatedXGBoostServicer(port, data_path), server)

    server_credentials = grpc.ssl_server_credentials(((_credentials.SERVER_CERTIFICATE_KEY, _credentials.SERVER_CERTIFICATE),))
    server.add_secure_port('[::]:' + port, server_credentials)

    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    assert len(sys.argv) == 3, "usage - python3 grpc_worker.py <PORT> <PATH TO DATA>"
    start_worker(sys.argv[1], sys.argv[2])
