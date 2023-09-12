import discord
import asyncio
import random
import pytz
import openai
import json
from datetime import datetime
from discord import app_commands
from discord.utils import get
from discord.ext import tasks
from src.bot import CHAT_MODEL
from bots.rhulk import rhulk
from bots.calus import calus
from bots.drifter import drifter

#* Creates the prompt for generating the random conversation
def create_prompt(first_speaker, topic):
    character_info = json.load(open('src/conversation_info.json'))
    num_additional_chars = random.randint(1, len(character_info) - 1)
    active_characters = {}
    while len(active_characters) < num_additional_chars:
        k, v = random.choice(list(character_info.items()))
        if k not in active_characters:
            active_characters[k] = v
    characters = "Characters: {}".format(character_info[first_speaker]["character"])
    personalities = character_info[first_speaker]["personality"]
    intros = character_info[first_speaker]["intro"]
    formatting = "Format as {}: TEXT".format(first_speaker)
    for char in active_characters:
        characters += "; {}".format(character_info[char]["character"])
        personalities += ". {}".format(character_info[char]["personality"])
        intros += "; {}".format(character_info[char]["intro"])
        formatting += ", {}: TEXT".format(char)
    
    prompt = ("Create dialogue set in Destiny universe. {}. {}. {}. "
    "Topic: {}. Stay on topic. Be extremely entertaining, creative, and funny. {}. " 
    "Limit conversation to be under 10 lines of dialogue. {} starts.").format(characters, intros, personalities, topic, formatting, first_speaker)
    return prompt

#* Generating the new random conversation
def generate_random_conversation(first_speaker="Rhulk", topic=None):
    log = open('log.txt', 'a')
    try:
        if topic == None:
            topics = json.load(open('topics.json'))
            weights = {}
            for _, (k, v) in enumerate(topics.items()):
                weights[k] = v["weight"]
            chosen_key = random.choices(list(weights.keys()), weights=list(weights.values()))[0]
            chosen_topic = topics[chosen_key]["topics"][random.randint(0, len(topics[chosen_key]["topics"]) - 1)]
        else:
            chosen_topic = topic
        prompt = create_prompt(first_speaker, chosen_topic)
        completion = openai.ChatCompletion.create(
            model=CHAT_MODEL,
            messages=[{'role':'system', 'content': prompt}],
            n=1,
            temperature=1.1,
            frequency_penalty=0.2,
            max_tokens=750
        )
        
        convo = (completion.choices[0].message.content).splitlines()
        while "" in convo:
            convo.remove("")
            
        log.write(f'Generated a conversation with the topic: {chosen_topic}: \n{convo}\n\n')
        
        formatted_convo = []
        for line in convo:
            if "Rhulk: " in line:
                formatted_convo.append({'Rhulk': line.split(': ', 1)[1]})
            elif "Calus: " in line:
                formatted_convo.append({'Calus': line.split(': ', 1)[1]})
        
        log.close()
        return formatted_convo, chosen_topic
    except Exception as e:
        log.write('Encountered an error when generating a conversation: ' + e + '\n\n')
        log.close()
        return e

#? Random Conversation Commands

#* Manually generate a random or specific conversation with Rhulk being the first speaker
@rhulk.bot.tree.command(name="rhulk_start_conversation", description="Have Rhulk start a conversation with the other bots!")
@app_commands.describe(topic="What should the topic be about? Leave empty for a randomly picked one.")
async def rhulk_start_conversation(interaction: discord.Interaction, topic: str=None):
    log = open('log.txt', 'a')
    try:
        await interaction.response.defer()
        
        convo, chosen_topic = generate_random_conversation('Rhulk', topic)
        await interaction.followup.send(f'*{interaction.user.display_name} wanted to hear Calus and I\'s conversation about {chosen_topic}. Here is how it unfolded:*')
        for line in convo:
            if 'Rhulk' in line:
                async with rhulk.bot.get_channel(interaction.channel_id).typing():
                    await asyncio.sleep(0.03 * len(line['Rhulk']))
                await rhulk.bot.get_channel(interaction.channel_id).send(line['Rhulk'])
            elif 'Calus' in line:
                async with calus.bot.get_channel(interaction.channel_id).typing():
                    await asyncio.sleep(0.03 * len(line['Calus']))
                await calus.bot.get_channel(interaction.channel_id).send(line['Calus'])
            await asyncio.sleep(round(random.uniform(5.0, 10.0), 1))
        
    except Exception as e:
        log.write('Encountered an error in the Random Conversation Generation for Rhulk: ' + e + '\n\n')
        await interaction.followup.send('Hmmm, I do not quite remember how the conversation went. (Bug Radiolorian for future fixes)')
    log.close()

#* Manually generate a random or specific conversation with Calus being the first speaker
@calus.bot.tree.command(name="calus_start_conversation", description="Have Calus start a conversation with the other bots!")
@app_commands.describe(topic="What should the topic be about? Leave empty for a randomly picked one.")
async def calus_start_conversation(interaction: discord.Interaction, topic: str=None):
    log = open('log.txt', 'a')
    try:
        await interaction.response.defer()
        convo, chosen_topic = generate_random_conversation('Calus', topic)
        await interaction.followup.send(f'*{interaction.user.display_name}, my most loyal Shadow, asked Rhulk and I to talk about {chosen_topic}! Here is how that went:*')
        for line in convo:
            if 'Rhulk' in line:
                async with rhulk.bot.get_channel(interaction.channel_id).typing():
                    await asyncio.sleep(0.03 * len(line['Rhulk']))
                await rhulk.bot.get_channel(interaction.channel_id).send(line['Rhulk'])
            elif 'Calus' in line:
                async with calus.bot.get_channel(interaction.channel_id).typing():
                    await asyncio.sleep(0.03 * len(line['Calus']))
                await calus.bot.get_channel(interaction.channel_id).send(line['Calus'])
            await asyncio.sleep(round(random.uniform(5.0, 10.0), 1))
        
    except Exception as e:
        log.write('Encountered an error in the Random Conversation Generation for Calus: ' + e + '\n\n')
        await interaction.followup.send('Hmmm, I do not quite remember how the conversation went. (Bug Radiolorian for future fixes)')
    log.close()

#* Creating a new conversation at 1pm EST everyday
@tasks.loop(seconds = 45)
async def scheduledBotConversation():
    now = datetime.now(pytz.timezone('US/Eastern'))
    if now.hour == 13 and now.minute == 0:
        log = open('log.txt', 'a')
        try:
            if random.randint(0, 1) == 0:
                first_speaker = 'Rhulk'
            else:
                first_speaker = 'Calus'
                
            for guild in rhulk.bot.guilds:
                if guild.name == "Victor's Little Pogchamps":
                    channel_id = get(guild.channels, name="rhulky-whulky").id
                    break
            
            convo, _ = generate_random_conversation(first_speaker)
            
            for line in convo:
                if 'Rhulk' in line:
                    async with rhulk.bot.get_channel(channel_id).typing():
                        await asyncio.sleep(0.03 * len(line['Rhulk']))
                    await rhulk.bot.get_channel(channel_id).send(line['Rhulk'])
                elif 'Calus' in line:
                    async with calus.bot.get_channel(channel_id).typing():
                        await asyncio.sleep(0.03 * len(line['Calus']))
                    await calus.bot.get_channel(channel_id).send(line['Calus'])
                await asyncio.sleep(round(random.uniform(5.0, 10.0), 1))

            log.write('Finished random conversation topic as scheduled.\n\n')
        except Exception as e:
            log.write('Encountered an error in the Random Conversation Generation: ' + e + '\n\n')
        log.close()