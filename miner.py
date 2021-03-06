import hashlib
import time
import binascii
import requests
import os
import json
from src.utils import Generate
from Crypto.PublicKey import RSA
import random
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256
from multiprocessing import Process
from tqdm import tqdm

class Miner:

    def __init__(self):
        self.mining_mode = input("Please enter mining mode: pool or solo:\n")
        self.thread_number = input("Please enter the number of threads to use:\n")
        self.node = input('Please enter the address of a node to begin mining:\n')
        self.difficulty = self.get_difficulty()

        if not os.path.isfile('data/wallet.json'):
            Generate.generate_wallet()

        wallet_file = json.load(open('data/wallet.json', 'r'))
        self.private_key = RSA.import_key(wallet_file['private key'])
        self.public_key = RSA.import_key(wallet_file['public key'])
        self.public_key_hex = wallet_file['public key hex']
        self.public_key_hash = wallet_file['public key hash']

    def proof_of_work(self, last_proof):
        """
        Simple Proof of Work Algorithm:
         - Find a number p' such that hash(pp') contains leading 4 zeroes, where p is the previous p'
         - p is the previous proof, and p' is the new proof
        """

        proof = 0

        while self.valid_proof(last_proof, proof) is False:
            proof = random.randint(1, 9999999999)

        return proof


    def valid_proof(self, last_proof, proof):
        """
        Validates the Proof
        :param last_proof: Previous Proof
        :param proof: Current Proof
        :return: True if correct, False if not.
        """
        valid_guess = ""
        for i in range(self.difficulty):
            valid_guess += "0"
        guess = f'{last_proof}{proof}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:Miner.difficulty] == valid_guess

    def get_difficulty(self):
        value = requests.get(f'http://{self.node}/difficulty')
        if value.status_code == 200:
            return value.json()

    def get_last_block(self):

        response = requests.get(f'http://{self.node}/chain')

        if response.status_code == 200:
            length = response.json()['length']
            chain = response.json()['chain']

            return chain[length - 1]

    def get_last_proof(self):
        response = requests.get(f'http://{self.node}/proof')
        if response.status_code == 200:
            return response.json()
        else:
            print("couldn't obtain proof")

    def get_last_hash(self):
        last_block = self.get_last_block()
        last_block_hash = last_block['current_hash']
        return last_block_hash

    def sign_transaction_data(self, data):
        transaction_bytes = json.dumps(data, sort_keys=True).encode('utf-8')
        hash_object = SHA256.new(transaction_bytes)
        signature = pkcs1_15.new(self.private_key).sign(hash_object)
        return signature

    def sign(self, data):
        signature_hex = binascii.hexlify(self.sign_transaction_data(data)).decode("utf-8")
        return signature_hex

    @staticmethod
    def hash(block):
        """
        Creates a SHA-256 hash of a Block
        :param block: Block
        """

        # We must make sure that the Dictionary is Ordered, or we'll have inconsistent hashes
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def solo_mine_loop(self):
        start_time = time.time()
        nonce_upper_limit = 9999999999
        process_id = random.randint(1, 99)
        while True:
            last_proof = self.get_last_proof()
            self.difficulty = self.get_difficulty()
            print(f'\nLast Proof: {last_proof}\nDifficulty: {self.difficulty}')
            current_time = time.time()

            if current_time - start_time > 3000:
                print("expanding upper nonce limit")
                new_upper_limit = str(nonce_upper_limit) + str(9)
                nonce_upper_limit = int(new_upper_limit)
                start_time = current_time
                print(f'upper nonce limit now: {nonce_upper_limit}')

            for i in tqdm(range(10000000), unit="H", unit_scale=1, desc=f"Mining Process ID {process_id}"):

                proof = random.randint(1, nonce_upper_limit)
                if self.valid_proof(last_proof, proof):
                    print('Proof Found: ', proof)
                    headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}

                    proof_transaction = {
                        'proof': proof,
                        'last_proof': last_proof,
                        'public_key_hash': self.public_key_hash,
                        'public_key_hex': self.public_key_hex,
                        'previous_block_hash': self.get_last_hash()
                    }

                    proof_signature = self.sign(proof_transaction)

                    proof_transaction_with_sig = {
                        'proof': proof,
                        'last_proof': last_proof,
                        'public_key_hash': self.public_key_hash,
                        'public_key_hex': self.public_key_hex,
                        'previous_block_hash': self.get_last_hash(),
                        'signature': proof_signature
                    }

                    response = requests.post(f'http://{self.node}/miners', json=proof_transaction_with_sig,
                                             headers=headers)

                    if response.status_code == 200:
                        print('\nSOLO: New Block Forged! Proof Accepted ', proof)
                        nonce_upper_limit = 9999999999
                        start_time = current_time
                        last_proof = self.get_last_proof()
                        self.difficulty = self.get_difficulty()

                    if response.status_code == 400:
                        print("\nSOLO: stale proof submitted, getting new proof")
                        nonce_upper_limit = 9999999999
                        start_time = current_time
                        last_proof = self.get_last_proof()
                        self.difficulty = self.get_difficulty()

    def pool_mine_loop(self):
        shares = []

        while True:
            self.difficulty = self.get_difficulty()
            difficulty = self.difficulty
            last_proof = self.get_last_proof()
            print(f'Last Proof: {last_proof}\nDifficulty: {self.difficulty}')
            job_request = requests.get(f'http://{self.node}/getjob')
            job = job_request.json()
            lower_limit = job['lower']
            upper_limit = job['upper']
            pool_diff = difficulty - 1
            valid_share = ""
            for i in range(pool_diff):
                valid_share += "0"
            process_id = random.randint(10, 99)

            for proof in tqdm(range(lower_limit, upper_limit), unit="H", unit_scale=1, desc=f"Mining Process ID {process_id}"):
                proof_to_be_hashed = int(str(last_proof) + str(proof))
                hashed_proof = self.hash(proof_to_be_hashed)

                if hashed_proof[:pool_diff] == valid_share:
                    share = {
                        'proof': proof,
                        'last_proof': last_proof,
                        'public_key_hash': self.public_key_hash,
                        'proof_hash': hashed_proof
                    }

                    shares.append(share)
                if self.valid_proof(last_proof, proof):
                    print('Proof Found: ', proof)
                    headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
                    requests.post(f'http://{self.node}/submit', json=shares)
                    shares = []
                    proof_transaction = {
                        'proof': proof,
                        'last_proof': last_proof,
                        'public_key_hash': self.public_key_hash,
                        'public_key_hex': self.public_key_hex,
                        'previous_block_hash': self.get_last_hash()
                    }

                    proof_signature = self.sign(proof_transaction)

                    proof_transaction_with_sig = {
                        'proof': proof,
                        'last_proof': last_proof,
                        'public_key_hash': self.public_key_hash,
                        'public_key_hex': self.public_key_hex,
                        'previous_block_hash': self.get_last_hash(),
                        'signature': proof_signature
                    }

                    response = requests.post(f'http://{self.node}/submit/proof', json=proof_transaction_with_sig,
                                             headers=headers)

                    if response.status_code == 200:
                        print('POOL: New Block Forged! Proof Accepted ', proof)
                        time.sleep(5)

                    if response.status_code == 400:
                        print("POOL: stale proof submitted, getting new proof")
                        self.difficulty = self.get_difficulty()
                        last_proof = self.get_last_proof()



            if len(shares) > 1:
                requests.post(f'http://{self.node}/submit', json=shares)
                print("finished processing job, now sharing with pool")

                # clear the list storing our generated shares after sharing them
                # with the pool or receiving a stale 400 code
                print("Share Broadcast Complete")
                shares = []



    def mine(self):

        if self.mining_mode == "pool":
            processes = []
            for i in range(int(self.thread_number)):
                p = Process(target=self.pool_mine_loop)
                processes.append(p)
                p.start()

            for p in processes:
                p.join()




        if self.mining_mode == 'solo':

            processes = []
            for i in range(int(self.thread_number)):
                p = Process(target=self.solo_mine_loop)
                processes.append(p)
                p.start()

            for p in processes:
                p.join()



Miner = Miner()

Miner.mine()
