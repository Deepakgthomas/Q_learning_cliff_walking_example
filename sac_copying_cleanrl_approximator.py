# Following the algorithm from here - https://spinningup.openai.com/en/latest/algorithms/sac.html
#Took ideas from -
#1. https://github.com/higgsfield/RL-Adventure-2/blob/master/7.soft%20actor-critic.ipynb
#2. https://github.com/vwxyzjn/cleanrl/blob/master/cleanrl/sac_continuous_action.py
#3. https://github.com/openai/spinningup/blob/master/spinup/algos/pytorch/sac/core.py

# Here we import all libraries

#todo How do I deal with starting states? Spinning Up spoke about applying entropy to starting states.
import numpy as np
import gym
import matplotlib.pyplot as plt
import os
import torch
import random
from torch import nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms
from collections import deque
from torch.distributions.normal import Normal
import torchvision as tv
import torch.nn.functional as F
import torch.optim as optim
import sys
import os
value_lr = 2.5e-4
policy_lr = 2.5e-4
batch_size = 500
episodes = 1000
ent_coeff = 0.2 #taken from cleanrl
gamma = 0.99
Q_learning_rate = 2.5e-4
replay_buffer = deque(maxlen=10000000)
mem_size = 1000
polyak = 0.995
PATH = "/saved_models/pong_batch_size_35"
os.makedirs(PATH, exist_ok = True)
tot_rewards = []
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

env = gym.make("Pendulum-v1")
act_limit = env.action_space.high[0]
act_rescale = (env.action_space.high - env.action_space.low) / 2.0
act_bias = (env.action_space.high + env.action_space.low) / 2.0
print("act_rescale = ", act_rescale)
print("act_bias = ", act_bias)

# print("act_limit = ", act_limit)
# print("env.observation_space.shape = ", env.observation_space.shape[0])
# print("env = ", env.action_space.shape[0])
class Q_function(nn.Module):
    def __init__(self, state_size, action_size, init_w = 3e-3):
        super(Q_function, self).__init__()
        self.state_size = state_size
        self.action_size = action_size
        self.linear_relu_stack = nn.Sequential(
            nn.Linear(state_size+action_size, 300),
            nn.ReLU(),
            nn.Linear(300, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU()
        )
        self.last_linear = nn.Linear(128, 1)
        self.last_linear.weight.data.uniform_(-init_w, init_w)
        self.last_linear.bias.data.uniform_(-init_w, init_w)
    def forward(self, state, action):
        x = torch.cat((state, action),1)
        x = self.linear_relu_stack(x)
        x = self.last_linear(x)
        return x
LOG_STD_MAX = 2
LOG_STD_MIN = -5
#Took this network from cleanrl
class PolicyNetwork(nn.Module):
    def __init__(self, dim_state, dim_action, act_limit, init_w=3e-3):
        super(PolicyNetwork,self).__init__()
        self.linear1 = nn.Linear(dim_state, 256)
        self.linear2 = nn.Linear(256, 256)
        self.mean = nn.Linear(256,1)
        self.std = nn.Linear(256,1)


    def forward(self, x):
        x = F.relu(self.linear1(x))
        x = F.relu(self.linear2(x))
        mean = self.mean(x)
        std = self.std(x)
        #todo Fix this
        std = torch.tanh(std)
        normal = torch.distributions.Normal(mean, 2)
        x_t = normal.rsample()
        y_t = torch.tanh(x_t)
        action = y_t
        log_prob = normal.log_prob(x_t)
        # Enforcing Action Bound
        log_prob -= torch.log(act_limit * (1 - y_t.pow(2)) + 1e-6)
        log_prob = log_prob.sum(1, keepdim=True)

        mean = torch.tanh(mean) * act_limit
        return action, log_prob

Q1 = Q_function(env.observation_space.shape[-1], 1).to(device)
target_Q1 = Q_function(env.observation_space.shape[-1], 1).to(device)
Q2 = Q_function(env.observation_space.shape[-1], 1).to(device)
target_Q2 = Q_function(env.observation_space.shape[-1], 1).to(device)

policy = PolicyNetwork(env.observation_space.shape[0], 2, act_limit).to(device)
Q1_opt = torch.optim.Adam(params = Q1.parameters(), lr = Q_learning_rate)
policy_opt = torch.optim.Adam(params = policy.parameters(), lr = policy_lr)



for target_param, online_param in zip(target_Q1.parameters(), Q1.parameters()):
    target_param.data.copy_(online_param)

for target_param, online_param in zip(target_Q2.parameters(), Q2.parameters()):
    target_param.data.copy_(online_param)
def update():
    with torch.no_grad():
        state, next_state, reward, done, action = zip(*random.sample(replay_buffer, batch_size))
        state = torch.stack(list(state), dim=0).squeeze(1).reshape(batch_size, -1).to(device)
        # print("state shape = ", state.shape)
        next_state = torch.from_numpy(np.array(next_state)).reshape(batch_size, -1).type(torch.float32).to(device)
        # print("next_state shape = ", next_state.shape)

        reward = torch.from_numpy(np.array(reward)).to(device)
        # print("reward shape = ", reward.shape)


        action = torch.from_numpy(np.array(action)).reshape(-1,1).to(device)
        # print("action shape = ", action.shape)


        done = torch.from_numpy(np.array(done)).long().to(device)
        # print("done shape = ", done.shape)


    # a'^{~}
    curr_policy_next_action = policy(next_state)[0]
    # print("curr_policy_next_action = ", curr_policy_next_action.shape)
    # a^{~}
    curr_policy_action = policy(state)[0]
    # print("curr_policy_action = ", curr_policy_action.shape)

    # Q_1(s,a)
    current_Q_1 = Q1(state, action).squeeze()
    # Q_2(s,a)
    current_Q_2 = Q2(state, action).squeeze()

    # Q1(s, a^{~})
    current_Q_new_1 = Q1(state, curr_policy_action).squeeze()
    # Q2(s, a^{~})
    current_Q_new_2 = Q2(state, curr_policy_action).squeeze()

    # print("current_Q_new = ", current_Q_new.shape)

    # Q1(s', a'^{~})
    next_state_Q_1 = target_Q1(next_state, curr_policy_next_action).squeeze()
    # Q2(s', a'^{~})
    next_state_Q_2 = target_Q2(next_state, curr_policy_next_action).squeeze()
    # print("next_state_Q = ", next_state_Q.shape)
    log_probs_next_action = policy(next_state)[1]

    log_probs_current_action = policy(state)[1]
    # y(r, s', d)
    target = reward + gamma*(1-done)*(torch.min(next_state_Q_1, next_state_Q_2) - ent_coeff*log_probs_next_action)

    # Q_loss = ((current_Q - target)**2).mean()
    # Q1_opt.zero_grad()
    # Q_loss.backward()
    # Q1_opt.step()
    # policy_loss = (current_Q_new-ent_coeff*torch.log(policy(next_state)[1])).mean()
    # policy_opt.zero_grad()
    # policy_loss.backward()
    # policy_opt.step()



    # Simulataenously summing both Q and policy loss. Otherwise, I was getting an error
    total_loss = ((current_Q_1 - target)**2).mean() + ((current_Q_2 - target)**2).mean() + (torch.min(current_Q_new_1, current_Q_new_2)-ent_coeff*log_probs_current_action).mean()
    Q1_opt.zero_grad()
    policy_opt.zero_grad()
    total_loss.backward()
    Q1_opt.step()
    policy_opt.step()

    with torch.no_grad():
        for target_param, online_param in zip(target_Q1.parameters(), Q1.parameters()):
            target_param.data.mul_(polyak)
            target_param.data.add_(online_param.data * (1 - polyak))

        for target_param, online_param in zip(target_Q2.parameters(), Q2.parameters()):
            target_param.data.mul_(polyak)
            target_param.data.add_(online_param.data * (1 - polyak))
check_learning_start = True
for i in range(episodes):
    print("i = ", i)
    state = torch.tensor(env.reset(), dtype=torch.float32).unsqueeze(0)

    eps_rew = 0
    done = False
    while not done:

        action = policy(state.to(device))[0].cpu().detach().numpy().reshape(-1)
        next_state, reward, done, _ = env.step(action)
        # print("reward = ", reward)
        replay_buffer.append((state, next_state, reward, done, action))
        eps_rew += reward
        if done:
            tot_rewards.append(eps_rew)
            break
        if len(replay_buffer)>mem_size and check_learning_start:
            print("The learning process has started")
            check_learning_start = False

        if len(replay_buffer)>mem_size:
            update()
        state = torch.tensor(next_state, dtype=torch.float32).squeeze().unsqueeze(0)
    print("Episode reward = ", eps_rew)
    tot_rewards.append(eps_rew)

    if(i%10==0 and i>0):
        plt.scatter(np.arange(len(tot_rewards)), tot_rewards)
        plt.show(block=False)
        plt.pause(3)
        plt.close()
        torch.save(policy.state_dict(), PATH)
        torch.save(Q1.state_dict(), PATH)
        torch.save(Q2.state_dict(), PATH)



