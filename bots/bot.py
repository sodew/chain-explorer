import discord
import json
import requests
import aiohttp
import re
import datetime
import openai
from pprint import pprint
from web3 import Web3
import pickle

from openai.error import RateLimitError
import asyncio

import os
from dotenv import load_dotenv

load_dotenv()

# Load tokens from .env file
discord_token = os.getenv('DISCORD_TOKEN')
openai_token = os.getenv('OPENAI_API_KEY')
passport_token = os.getenv('PASSPORT_API_KEY')
scorer_token = os.getenv('PASSPORT_SCORER')

# Setup Passport API
if passport_token:
    passport_headers = {
        'Content-Type': 'application/json',
        'X-API-Key': passport_token
    }

# Setup OpenAI API
openai.api_key = openai_token

# Setup Alechmy API
alchemy_url = "https://eth-mainnet.g.alchemy.com/v2/kyvyHty9Uu7gLaas166z5rFBPsxQDDqT"
w3 = Web3(Web3.HTTPProvider(alchemy_url))


def parse_api_response(response):
    wallet_address = response["story"]["walletId"]
    ens_domain = response["story"]["ensName"]
    creation_date = datetime.datetime.fromtimestamp(
        response['story']['walletDOBTimestamp']).strftime("%B %d, %Y")
    latest_transaction_date = datetime.datetime.fromtimestamp(
        response['story']['latestTransactionDateTimestamp']).strftime("%B %d, %Y")

    passport = ""
    print(response["passport"])
    if response["passport"]:
        passport_score = response["passport"]["score"]
        passport_timestamp = datetime.datetime.fromisoformat(
            response["passport"]["last_score_timestamp"]).strftime("%B %d, %Y")
        passport = f"They have a Gitcoin Passport score of {passport_score} as of {passport_timestamp}"
    else:
        print("no passport response")

    number_of_nfts = response["story"]["numberOfNftsOwned"]

    def generate_title_list(data):
        if data:
            return '\n'.join([f"• {ach['title']}" for ach in data])
        else:
            return "No data found."

    def generate_description_list(data):
        if data:
            return '\n'.join([f"• {ach['description']}" for ach in data])
        else:
            return "No data found."

    def generate_info_list(data):
        if data:
            return '\n'.join([f"• {ach['title']} : {ach['description']}" for ach in data])
        else:
            return "No achievements found."

    nft_achievements = generate_description_list(
        response["story"]["nftAchievements"])
    defi_achievements = generate_description_list(
        response["story"]["deFiAchievements"])
    community_achievements = generate_description_list(
        response["story"]["communityAchievements"])
    vibe_achievements = generate_info_list(
        response["story"]["vibeAchievements"])

    return (
            f"The wallet {wallet_address} belongs to **{ens_domain}**. This wallet was "
            f"created on {creation_date} and their latest transaction was on {latest_transaction_date}.\n\n"
            f"They own {number_of_nfts} NFTs including:\n{nft_achievements}\n\n"
            f"## **Evidence of their participation in DeFi and money markets**:\n{defi_achievements}\n\n"
            f"## **Evidence of participation in web3 communities**:\n{community_achievements}\n\n"
            f"## **Evidence of engagements within the web3 ecosystem**:\n{vibe_achievements}\n\n"
            f"### **{passport}**"
        )

def parse_passport(response):
    items = []
    for item in response["items"]:
        if item['metadata']:
            name = item['metadata']['name']
            desc = item['metadata']['description']
            pprint(name)
            items.append(f"* **{name}**: {desc}")

    full_message = f"## **They own the following stamps:**\n" + \
    "\n".join(items)

    # Splitting the message into 2000 characters chunks
    return [full_message[i:i+1800] for i in range(0, len(full_message), 1800)]

    # return (
    #     f"They have the following Gitcoin Passport stamps:\n"
    #     + "\n".join(items))


class ChatBot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_responses = {}  # A dictionary to cache API responses

    async def on_ready(self):
        print("Bot is ready!")

    async def on_message(self, message):
        if message.author == self.user:  # Ignore bot's own messages
            return

        if message.content.startswith("!cache"):
            print("CACHE: \n")
            pprint(self.api_responses)
            # If the cache is empty, return None
            if not self.api_responses:
                return None

            addresses = list(self.api_responses.keys())
            await message.channel.send(f"addresses: {addresses}")
            await message.channel.send(f'latest wallet address = {addresses[-1]}')


        if '0x' in message.content or '.eth' in message.content:
            eth_address_pattern = re.compile(r"0x[a-fA-F0-9]{40}")
            eth_domain_pattern = re.compile(r"\b\w+\.eth\b")
            address = ''

            if '0x' in message.content:
                address_match = re.search(eth_address_pattern, message.content)
                if address_match:
                    address = address_match.group()
                    # await message.channel.send(f"Address: {address}")

            elif '.eth' in message.content:
                domain_match = re.search(eth_domain_pattern, message.content)
                if domain_match:
                    address = domain_match.group()
                    # await message.channel.send(f"Address: {address}")

            await message.channel.send(f"Fetching on-chain data from {address}. This may take a moment...")

            # Check if the data for this address is already in cache
            if address in self.api_responses:
                await message.channel.send(f"{address} in cache")
                await message.channel.send(parse_api_response(self.api_responses[address]))
                return

            CHAINSTORY_URI = f"https://www.chainstory.xyz/api/story/getStoryFromCache?walletId={address}"

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(CHAINSTORY_URI) as response:
                        if response.status != 200:
                            await message.channel.send(f"Error {response.status}: Unable to retrieve chainstory for the provided ethereum address.")
                            return

                        data = await response.json()

                if data.get('success') and data.get('story'):
                    pprint(data)
                    self.api_responses[address] = data

                    # Retrieve more data from Gitcoin Passport
                    passport_address = data["story"]["walletId"]
                    print(passport_address)
                    GET_PASSPORT_SCORE_URI = f"https://api.scorer.gitcoin.co/registry/v2/score/{scorer_token}/{passport_address}"

                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(GET_PASSPORT_SCORE_URI, headers=passport_headers) as passport_response:
                                if passport_response.status == 200:
                                    passport_data = await passport_response.json()
                                    # await message.channel.send(f"User {address} has a Gitcoin Passport")

                                    # Adding the passport score data into the nested dictionary
                                    self.api_responses[address]['passport'] = passport_data
                                else:
                                    self.api_responses[address]['passport'] = {
                                    }
                                    print(
                                        f"Error {passport_response.status}: Unable to retrieve passport score for the address.")
                                    await message.channel.send(f"User {address} does not have a Gitcoin Passport")

                    except Exception as e:
                        await message.channel.send(f"Error fetching passport score: {str(e)}")

                    # with open('local_state.pkl', 'wb') as f:
                    #     pickle.dump(self.api_responses, f)
                    await message.channel.send(parse_api_response(self.api_responses[address]))
                else:
                    await message.channel.send("Unable to retrieve chain information for the provided wallet address.")

            except Exception as e:
                error_msg = f"Error fetching data: {str(e)}"
                print(error_msg)
                await message.channel.send(error_msg)

        # passport stamps prompt
        if message.content.startswith("!passport stamps"):
            if not self.api_responses:
                return None
            
            cached_addresses = list(self.api_responses.keys())
            latest_address = cached_addresses[-1]
            address = self.api_responses[latest_address]['story']['walletId']
            await message.channel.send(address)

            GET_PASSPORT_STAMPS_URI = f"https://api.scorer.gitcoin.co/registry/stamps/{address}?limit=1000&include_metadata=true"

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(GET_PASSPORT_STAMPS_URI, headers=passport_headers) as response:
                        if response.status != 200:
                            await message.channel.send(f"Error {response.status}: Unable to retrieve passport for the provided address.")
                            return

                        data = await response.json()
                        pprint(data)
                        # Check if the data is not None
                        if data is not None:
                            await message.channel.send(f"Successfully got passport data!")

                            passport_data_chunks = parse_passport(data)
                            for chunk in passport_data_chunks:
                                await message.channel.send(chunk)
                        else:
                            await message.channel.send(f"Error: Passport data is None")

            except Exception as e:
                await message.channel.send(f"Error fetching data: {str(e)}")

        # alchemy prompt
        if message.content.startswith("!alchemy"):
            if not self.api_responses:
                return None
            
            cached_addresses = list(self.api_responses.keys())
            latest_address = cached_addresses[-1]
            address = self.api_responses[latest_address]['story']['walletId']
            # print("is connected? " + w3.is_connected())
            await message.channel.send(f"is connected? " + str(w3.is_connected()))
            await message.channel.send(f"ETH balance: " + str(w3.eth.get_balance(address)))


        if message.content.startswith("!explain "):
            query = message.content[len("!explain "):]
            prompt = f"I want you to act as a blockchain expert. Explain {query} "
            try:
                response = openai.Completion.create(
                    model="text-davinci-003", prompt=prompt, temperature=0.6, max_tokens=200)
                await message.channel.send(response.choices[0].text.strip())
            except RateLimitError:
                await message.channel.send("Sorry, I'm getting too many requests right now. Please try again later.")
                # Introducing a delay. Adjust as needed.
                await asyncio.sleep(10)


if __name__ == "__main__":
    intents = discord.Intents.default()
    intents.message_content = True
    bot = ChatBot(intents=intents)
    bot.run(discord_token)
