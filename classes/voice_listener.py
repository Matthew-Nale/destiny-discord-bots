import discord
import os
import wave
import string
import openai
import asyncio
import io
import aiohttp
import shlex
import subprocess
import random
import json

from bot_manager import BotManager
from discord.opus import Encoder
from discord import app_commands
from datetime import datetime
from discord.ext import voice_recv, commands, tasks

INSTRUCTION_PROMPT = ("You are in a Discord call with other members, and you will be provided "
                     "the different users as well as what they said. Address the person you are speaking to. "
                     "The ordering of the sentences and users may not correspond with the actual "
                     "spoken order. Only respond with any input you may have, limiting your response to under 250 characters.")

MAX_LISTENS = 5
MIN_LISTENS = 3
LISTEN_TIME = 4
JOIN_CHANCE = 0.15
COOLDOWN_TIME_HOURS = 1
MAX_JOIN_LIMIT = 3

# Needed for specific streaming AudioSource
class StreamingAudio(discord.AudioSource):
    def __init__(self, source, *, executable='ffmpeg', pipe=False, stderr=None, before_options=None, options=None):
        stdin = None if not pipe else source
        args = [executable]
        if isinstance(before_options, str):
            args.extend(shlex.split(before_options))
        args.append('-i')
        args.append('-' if pipe else source)
        args.extend(('-f', 's16le', '-ar', '48000', '-ac', '2', '-loglevel', 'warning'))
        if isinstance(options, str):
            args.extend(shlex.split(options))
        args.append('pipe:1')
        self._process = None
        try:
            self._process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)
            self._stdout = io.BytesIO(
                self._process.communicate(input=stdin)[0]
            )
        except FileNotFoundError:
            raise discord.ClientException(executable + ' was not found.') from None
        except subprocess.SubprocessError as exc:
            raise discord.ClientException('Popen failed: {0.__class__.__name__}: {0}'.format(exc)) from exc
    def read(self):
        ret = self._stdout.read(Encoder.FRAME_SIZE)
        if len(ret) != Encoder.FRAME_SIZE:
            return b''
        return ret
    def cleanup(self):
        proc = self._process
        if proc is None:
            return
        proc.kill()
        if proc.poll() is None:
            proc.communicate()

        self._process = None


class VoiceRecording(commands.Cog):    
    
    def __init__(self, bot: BotManager):
        self.bot = bot
        self.join_conversation.start()
        with open('data/voice_conversations.json', "r") as f:
                self.registered_users = json.load(f)["registered_users"]
        

    @tasks.loop(minutes=40)
    async def join_conversation(self):
        try:
            active_voice_channel = await self.get_active_vc()
            
            if await self.can_join(active_voice_channel):
                self.voice_packets = {}
                self.audio_files = {}
                self.transcription = []
                self.voice_channel = await active_voice_channel.connect(cls=voice_recv.VoiceRecvClient)
                
                for _ in range(0, random.randint(MIN_LISTENS, MAX_LISTENS)):
                    await self.listen_for(LISTEN_TIME)
                    
                    await self.transcribe_audio()
                    response = await self.generate_response()
                    await self.play_audio(response)
                    self.voice_channel.stop_listening()
                
                await self.cleanup()
        except Exception as e:
            self.bot.log_handler.error(f'Encountered an error in joining conversation: {e}')
        
        await self.voice_channel.disconnect()
    
    
    async def can_join(self, active_voice_channel) -> bool:
        if active_voice_channel is None or random.random() < JOIN_CHANCE:
            return False
        return True
        

    async def get_active_vc(self):
        try:
            valid_channels = []
            for server in self.bot.guilds:
                for channel in server.voice_channels:
                    if len([member for member in channel.members if member.id in self.registered_users]) > 0:
                        valid_channels.append(channel)
            
            return random.choice(valid_channels)
        except:
            return None


    async def listen_for(self, time):

        def save(data: voice_recv.VoiceData):
            if data.source.id in self.registered_users:
                self.voice_packets[data.source.display_name].append(data)
        
        for member in self.voice_channel.channel.members:
            self.voice_packets[member.display_name] = []
            
        self.voice_channel.listen(voice_recv.BasicSink(save))
        
        await asyncio.sleep(time)
    
    
    async def transcribe_audio(self):
        try:
            packets_to_process = self.voice_packets
            translator = str.maketrans('', '', string.punctuation)
            
            for member, packets in packets_to_process.items():
                self.voice_packets[member] = self.voice_packets[member][len(packets):]
                if len(packets) > 5:
                    cleaned_words = [word.translate(translator) for word in member.split()]
                    filename = ''.join(cleaned_words) + '.wav'
                    
                    with wave.open(filename, 'wb') as file:
                        file.setparams((2, 2, 44100, 0, 'NONE', 'NONE'))
                        for data in packets:
                            file.writeframes(data.pcm)
                        self.audio_files[member] = filename
            
            for member, file in self.audio_files.items():
                with open(file, 'rb') as file:
                    self.transcription.append({member: openai.audio.transcriptions.create(
                        model="whisper-1",
                        file=file
                    ).text})
        except Exception as e:
            self.bot.log_handler.error(f'Encountered an error when transcibing audio:\n{e}')
    
    
    async def cleanup(self):
        try:
            for file in self.audio_files.values():
                os.remove(file)
        except Exception as e:
            self.bot.log_handler.error(f'Encountered an error when cleaning up files:\n{e}')
    
    
    async def generate_response(self):
        try:
            instructions = self.bot.text.chat_prompt + INSTRUCTION_PROMPT
            messages = [{"role": "system", "content": instructions}]
            
            for audio in self.transcription:
                for member, text in audio.items():
                    if member != self.bot.name:
                        messages.append({"role": "user", "content": '{}: {}'.format(member, text)})
                    else:
                        messages.append({"role": "assistant", "content": text})
            
            response = self.bot.text_handler.generate(messages)
                    
            self.transcription.append({self.bot.name: response})
            
            return response
        except Exception as e:
            self.bot.log_handler.error(f'Encountered an exception when generating a text response:\n{e}')


    async def play_audio(self, response):
        try:
            body = {'text': response,
                    'model_id': self.bot.voice_model,
                    'voice_settings': {'stability': 0.15,
                                    'similarity_boost': 0.7,
                                    'style': 0.1,
                                    'use_speaker_boost': True
                                    }
                    }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url='https://api.elevenlabs.io/v1/text-to-speech/' + self.bot.voice_handler.voice['voice_id'] + '/stream?optimize_streaming_latency=3',
                                        headers={'XI-API-KEY': self.bot.voice_handler.api_key},
                                        json=body) as r:
                    content = io.BytesIO(await r.read())
                    self.voice_channel.play(StreamingAudio(content.read(), pipe=True))
            
            while self.voice_channel.is_playing():
                await asyncio.sleep(1)
                
        except Exception as e:
            self.bot.log_handler.error(f'Encountered an exception when playing response:\n{e}')