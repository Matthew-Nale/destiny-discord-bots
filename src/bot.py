import os
import discord
import openai
import asyncio
import string

from datetime import datetime
from discord.ext import commands, tasks
from dotenv import load_dotenv
from src.external_api import ElevenLabs

#? Initializations and global values

#* Load and set env variables for API calls
load_dotenv()
GPT_KEY = os.getenv('CHATGPT_TOKEN')
openai.api_key = GPT_KEY
DEFAULT_VC = os.getenv('DEFAULT_VOICE_CHANNEL_ID')

MAX_LEN = 1024 # Setting character limit for ElevenLabs
MAX_TOKENS = 128 # Setting token limit for ChatGPT responses
CHAT_MODEL = "gpt-4o-2024-08-06" # Model for OpenAI Completions to use

#? Bot Classes

class VoiceCommands:
    def __init__(self, _name:str, _voice_name:str, _voice_key:str, _voice_model:str, _status_messages:dict):
        self.name = _name
        self.elevenlabs = ElevenLabs(_voice_name, _voice_key)
        self.voice_model = _voice_model
        self.status_messages = _status_messages
    
    
    async def credits(self, interaction: discord.Interaction) -> (None):
        log = open("log.txt", "a")
        log.write(f'{interaction.user.global_name} asked {self.name} for his ElevenLabs credits remaining.\n\n')
        
        user = await self.elevenlabs.get_user()
        char_remaining = user['character_limit'] - user['character_count']
        
        if char_remaining:
            await interaction.response.send_message(f'I will still speak {char_remaining} characters. Use them wisely.', ephemeral=True)
        else:
            await interaction.response.send_message('{} (Reached character quota for this month)'.format(self.status_messages['credits']))
            
        log.close()
    
    
    async def speak(self, interaction: discord.Interaction, text: str, stability: float, clarity: float, style: float) -> (None):
        log = open("log.txt", "a")
        log.write(f'{interaction.user.global_name} asked {self.name} to say: `{text}`\n\n')
        
        await interaction.response.defer()
        
        if len(text) > MAX_LEN:
            log.write(f'Size of request was too long for /speak\n\n')
            await interaction.followup.send('{} Please limit your text to below {} characters. You are currently at {} characters.'.format(self.status_messages['speak']['too_long'], MAX_LEN, len(text)))
            log.close()
            return
        
        try:
            audio = await self.elevenlabs.generate(
                text=text,
                model=self.voice_model,
                stability=stability,
                similarity_boost=clarity,
                style=style,
                use_speaker_boost=True
            )
            
            filename = f'{text.split()[0]}.mp3'
            split_text = text.split()
            
            if len(split_text) < 5:
                filename = f'{split_text[0]}.mp3'
            else:
                translator = str.maketrans('', '', string.punctuation)
                cleaned_words = [word.translate(translator) for word in split_text]
                filename = f'{cleaned_words[0]}_{cleaned_words[1]}_{cleaned_words[2]}_{cleaned_words[3]}_{cleaned_words[4]}.mp3'
                
            with open(filename, "wb") as f:
                    f.write(audio)
            await interaction.followup.send(file=discord.File(filename))
            
            log.write(f'/speak for {self.name}: Sent .mp3 titled `{filename}`.\n\n')
            os.remove(filename)
        except Exception as e:
            log.write(f'Error in /speak for {self.name}: \n{e}\n\n')
            await interaction.followup.send("{} (Something went wrong with that request)".format(self.status_messages['speak']['error']),
                                            ephemeral=True)
        log.close()
    
    
    async def vc_speak(self, interaction: discord.Interaction, text: str, vc: str=DEFAULT_VC, stability: float=0.2, clarity: float=0.7, style: float=0.1) -> (None):
        log = open("log.txt", "a")
        log.write(f'{interaction.user.global_name} asked {self.name} to say in the VC: `{text}`\n\n')
        
        await interaction.response.defer()
        
        if len(text) > MAX_LEN:
            log.write(f'Size of request was too long for /vc_speak\n\n')
            await interaction.followup.send('{} Please limit your text to below {} characters. You are currently at {} characters.'.format(self.status_messages['speak']['too_long'], MAX_LEN, len(text)))
            log.close()
            return
        
        if interaction.user.voice is None:
            channel = self.bot.get_channel(DEFAULT_VC)
        else:
            channel = interaction.user.voice.channel

        try:
            audio = await self.elevenlabs.generate(
                text=text,
                model=self.voice_model,
                stability=stability,
                similarity_boost=clarity,
                style=style,
                use_speaker_boost=True
            )
            
            filename = f'{text.split()[0]}.mp3'
            split_text = text.split()
            
            if len(split_text) < 5:
                filename = f'{split_text[0]}.mp3'
            else:
                translator = str.maketrans('', '', string.punctuation)
                cleaned_words = [word.translate(translator) for word in split_text]
                filename = f'{cleaned_words[0]}_{cleaned_words[1]}_{cleaned_words[2]}_{cleaned_words[3]}_{cleaned_words[4]}.mp3'
                
            with open(filename, "wb") as f:
                f.write(audio)
            
            vc = await channel.connect()
            await asyncio.sleep(1.5)
            vc.play(discord.FFmpegPCMAudio(source=filename))
            while vc.is_playing():
                await asyncio.sleep(1.5)
            vc.stop()
            await vc.disconnect()
            
            await interaction.followup.send(file=discord.File(audio))
            log.write(f'/vc_speak for {self.name}: Sent .mp3 titled `{filename}`.\n\n')
            os.remove(filename)
        except Exception as e:
            log.write(f'Error in /vc_speak for {self.name}: \n{e}\n\n')
            await vc.disconnect()
            await interaction.followup.send("{} (Something went wrong with that request)".format(self.status_messages['speak']['error']),
                                        ephemeral=True)
                
        log.close()


class TextCommands:
    memory = {}
    last_interaction = {}
    
    
    def __init__(self, _name:str, _chat_prompt:str, _status_messages:dict):
        self.name = _name
        self.chat_prompt = _chat_prompt
        self.status_messages = _status_messages
        
        
    async def prompt(self, interaction: discord.Interaction):
        log = open("log.txt", "a")
        log.write(f'{interaction.user.global_name} asked {self.name} for his ChatGPT Prompt.\n\n')
        
        await interaction.response.send_message("Here is the prompt used. Feel free to use this to generate text for the /speak or /vc_speak command: \n\n {}".format(self.chat_prompt), ephemeral=True)
        
        log.close()


    async def reset(self, interaction: discord.Interaction):
        log = open("log.txt", "a")
        
        self.memory[interaction.guild.id].clear()
        self.memory[interaction.guild.id].append({"role": "system", "content": self.chat_prompt})
        
        log.write(f'{interaction.user.global_name} cleared {self.name}\'s memory.\n\n')
        await interaction.response.send_message('{}'.format(self.status_messages['reset'].replace('{USERNAME}', interaction.user.display_name)))
        
        log.close()
    
    
    async def chat(self, interaction: discord.Interaction, prompt: str, temperature: float, frequency_penalty: float, presence_penalty: float):
        log = open("log.txt", "a")
        
        await interaction.response.defer()
        
        try:
            self.memory[interaction.guild.id].append({"role": "user", "content": prompt})
            
            completion = openai.chat.completions.create(
                model=CHAT_MODEL,
                messages=self.memory[interaction.guild.id],
                n=1,
                max_tokens=MAX_TOKENS,
                temperature=temperature,
                frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty
            )
            
            log.write(f'/chat for {self.name} prompt and user: \n{prompt}. From {interaction.user.global_name}.\n\n/chat output: \n{completion}\n\n')
            
            if completion.usage.total_tokens > 500:
                removed_user = self.memory[interaction.guild.id].pop(1)
                removed_assistant = self.memory[interaction.guild.id].pop(1)
                log.write(f'/chat for {self.name} token limit reached. Removed the user prompt: {removed_user}, and the assistant answer: {removed_assistant}\n\n')
            
            self.memory[interaction.guild.id].append({"role": "assistant", "content": completion.choices[0].message.content})
            await interaction.followup.send('{} *"{}"* \n\n{}'.format(self.status_messages['chat']['response'].replace('{USERNAME}', interaction.user.display_name),
                                                                                                           prompt,
                                                                                                           completion.choices[0].message.content))
            self.last_interaction[interaction.guild.id] = datetime.now()
        except Exception as e:
            log.write(f'/chat for {self.name} error: \n{e}\n\n')
            await interaction.followup.send("{} (Something went wrong)".format(self.status_messages['chat']['error']))
            
        log.close()
    

class Bot:
    def __init__(self, _name:str, _discord_token:str, _status_messages:dict=None, _voice_name:str=None, _voice_key:str=None,
                 _voice_model:str=None, _chat_prompt:str=None, _use_voice:bool=False, _use_text:bool=False):
        self.name = _name
        self.bot = commands.Bot(command_prefix=commands.when_mentioned_or('!{self.name}'), intents=discord.Intents.all())
        self.discord_token = _discord_token
        self.voice = VoiceCommands(_name, _voice_name, _voice_key, _voice_model, _status_messages) if _use_voice else None
        self.text = TextCommands(_name, _chat_prompt, _status_messages) if _use_text else None
        
        
    async def on_ready(self):
        log = open("log.txt", "a")
        log.write(f'{self.bot.user} has connected to Discord!\n\n')
        
        try:
            synced = await self.bot.tree.sync()
            log.write(f'Synced {len(synced)} commands for {self.bot.user}!\n\n')
        except Exception as e:
            log.write(f'{self.bot.user} on_ready error: \n{e}\n\n')
        log.close()
        
        if self.text is not None:
            await self.botInit()
            await self.cleanMemories.start()
    
    
    async def botInit(self):
        log = open("log.txt", "a")
        
        for server in self.bot.guilds:
            log.write(f'Setting up {self.name} context memory for server: {server.id} ({server.name})\n\n')
            self.text.memory[server.id] = [{"role": "system", "content": self.text.chat_prompt}]
            self.text.last_interaction[server.id] = datetime.now()
            
        log.close()
    
    
    @tasks.loop(hours = 6)
    async def cleanMemories(self):
        currentTime = datetime.now()
        
        for server in self.bot.guilds:
            time_diff = currentTime - self.text.last_interaction[server.id]
            if time_diff.days > 0 or (time_diff.seconds / 3600) >= 6:
                self.text.memory[server.id] = [{"role": "system", "content": self.text.chat_prompt}]
                self.text.last_interaction[server.id] = datetime.now()