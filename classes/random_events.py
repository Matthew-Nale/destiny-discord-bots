import logging
import datetime
import asyncio
import json
import random
import discord
import string
import openai
import wave
import os
import aiohttp
import io
import shlex
import subprocess
import time

from discord.ext import commands, tasks, voice_recv
from discord import Message
from pydub import AudioSegment
from discord.opus import Encoder


INSTRUCTION_PROMPT = ("You are in a Discord call with other members, and you will be provided "
                     "the different users as well as what they said. Address the person you are speaking to. "
                     "The ordering of the sentences and users may not correspond with the actual "
                     "spoken order. Only respond with any input you may have, limiting your response to under 250 characters.")

MAX_LISTENS = 4
MIN_LISTENS = 2
LISTEN_TIME = 3
VOICE_JOIN_CHANCE = 0.20
AUDIO_FILE_LOCATION = "temp_audio"

async def setup_cogs(client, talk_chance):
    """Sets up all Cog handlers for various random events. The list of current random events is as follows:
        - RandomTextEvents
        - RandomVoiceEvents

    Args:
        client (BotManager): A BotManager that is requesting the random events to be added.
        talk_chance (float): A float that determines the chance of randomly replying to text messages.
    """
    await client.add_cog(RandomTextEvents(client, talk_chance))
    await client.add_cog(RandomVoiceEvents(client))


class RandomTextEvents(commands.Cog):
    """Handles all generic random text events.

    Creates a new discord.commands.Cog object to handle all autonomous text events.
    To be added to the bot, it must be setup by using the default Discord.py add_cog() command

    Attributes:
        _bot: The BotManager object that is wanting to add the Cog. Used to handle discord.Interaction operations and interact with the text handler.
        _talk_chance: A float that determines the chance that the bot responds to a text message or joins active voice channels.
    """
    def __init__(self, _bot, _talk_chance: float):
        """Inits RandomTextEvents with the BotManager and talk chance."""
        self.bot_manager = _bot
        self.log_handler = logging.getLogger(self.bot_manager.name)
        self.talk_chance = _talk_chance

    @commands.Cog.listener("on_message")
    async def on_message(self, message: Message):
        """Listens to all text messages seen to potentially respond to one.

        Args:
            message (discord.Message): The message that was received in a valid text channel.
        """
        if not message.attachments and message.type != discord.MessageType.chat_input_command:
            if random.random() <= self.talk_chance:
                self.log_handler.info(f"A message in the channel \'{message.channel.name}\' triggered an automatic response.")
                past_messages = [m async for m in message.channel.history(after=datetime.datetime.now() - datetime.timedelta(hours=12), limit=5, oldest_first=False)]
                past_messages.reverse()
                response = await self.generate_text_response(past_messages)
                self.log_handler.info(f'Chiming-in on previous messages {[msg.content for msg in past_messages]} with bot: {self.bot_manager.name}. Response: {response}')
                await self.bot_manager.get_channel(message.channel.id).send(response, reference=message)
        await self.bot_manager.process_commands(message)

    async def generate_text_response(self, user_msgs: list):
        """Generates a response to the most recent messages in a text channel.

        Args:
            user_msgs (list): List of discord.Message objects from the most recent user messages.

        Returns:
            str: The string response that the BotManager should reply with.
        """
        try:
            messages = [{"role": "system", "content": self.bot_manager.text_handler.prompt + f"  You will be provided with a series of Discord in the format NAME: MESSAGE. Respond as {self.bot_manager.name}: MESSAGE."}]
            for msg in user_msgs:
                messages.append({"role": "user", "content": "{}: {}".format(msg.author.display_name, msg.content)})
            completion = await self.bot_manager.text_handler.generate(messages, 1.3, 0.9, 0.75)
            return completion.split(': ', 1)[1]
        except Exception as e:
            self.log_handler.error(f"Encountered an error when generating a random response: {e}")
            return e


class RandomVoiceEvents(commands.Cog):
    """Handles all generic random voice events.

    Creates a new discord.commands.Cog object to handle all autonomous voice events.
    To be added to the bot, it must be setup by using the default Discord.py add_cog() command.

    Attributes:
        _bot: The BotManager object that is wanting to add the Cog. Used to handle discord.Interaction operations and interact with the associated text/voice handlers.
    """
    
    def __init__(self, _bot):
        """Inits RandomVoiceEvents with the BotManager."""
        self.bot_manager = _bot
        self.log_handler = logging.getLogger(self.bot_manager.name)
        with open('../data/voice_conversations.json', "r") as f:
                self.registered_users = json.load(f)["registered_users"]
                
        self.add_command()
        self.random_voice_conversations.start()


    @tasks.loop(minutes=40)
    async def random_voice_conversations(self):
        """Setups timed loop to autonomously join in on potentially active voice channels."""
        chosen_voice_channel = await self.get_random_active_vc()
        
        if chosen_voice_channel is None or random.random() < VOICE_JOIN_CHANCE:
            return
        
        self.log_handler.info(f"Chose to join the voice channel \'{chosen_voice_channel.name}\' to have a random voice conversation.")
        self.voice_channel = await chosen_voice_channel.connect(cls=voice_recv.VoiceRecvClient)
        await self.automatic_voice_chat()
        await self.cleanup()

    def add_command(self):
        """Adds the command for directly requesting the bot to join the voice channel the user is in."""
        
        @self.bot_manager.tree.command(name=f"{self.bot_manager.name.lower()}_voice_chat", description=f"Manually force {self.bot_manager.name} to join your VC for a chat")
        async def force_join(interaction: discord.Interaction):
            """Begins the process of having the bot converse with the user's voice channel if they are present."""
            await interaction.response.defer()
            self.log_handler.info(f"{interaction.user.global_name} requested {self.bot_manager.name} to join their voice channel.")
            
            if interaction.user.id not in self.registered_users:
                    await interaction.followup.send("You must be a voice registered user to perform this command. Please register first")
                    self.log_handler.warning("User was not in a valid voice channel. Cancelling their request.")
                    return
            
            self.voice_channel = await interaction.user.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
            await self.automatic_voice_chat()

            await self.send_combined_audio()
            
            await self.cleanup()
    
    async def automatic_voice_chat(self):
        """Handles the autonomous voice interaction in the voice channel the bot is currently in."""
        try:
            self.transcription = []
            self.audio_files = {}
            self.new_audio = {}
            self.last_packet_location = {}
            
            for _ in range(random.randint(MIN_LISTENS, MAX_LISTENS)):
                self.log_handler.debug(f"Round {_ + 1} of listening to users.")
                await self.listen_for(LISTEN_TIME)
                self.log_handler.debug("Transcibing audio from all users.")
                await self.transcribe_audio()
                self.log_handler.debug("Generating a response from transcibed audio.")
                response = await self.generate_voice_response()
                self.log_handler.debug("Generating voice and playing response in the voice channel.")
                await self.play_audio(response)
                
            self.voice_channel.stop_listening()
        except Exception as e:
            self.log_handler.error(f'Encountered an error while in a voice conversation:\n{e}')
        
        self.log_handler.debug(f"Finished listending after {_ + 1} rounds. Cleaning up files and disconnecting from the voice channel.")
        await self.voice_channel.disconnect()

    async def get_random_active_vc(self):
        """Attempts to grab a random voice channel that has active members that are registered for voice commands."""
        try:
            valid_channels = []
            for server in self.bot_manager.guilds:
                for channel in server.voice_channels:
                    if len([member for member in channel.members if member.id in self.registered_users]) > 0:
                        valid_channels.append(channel)
            
            return random.choice(valid_channels)
        except:
            return None


    async def listen_for(self, time):
        """Listens to the current voice channel for a specified amount of time.

        Args:
            time (float): A float that determines how long to wait before generating a response in seconds.
        """

        if not self.voice_channel.is_listening():
            self.sink = ContinuousWaveSink()
            self.voice_channel.listen(self.sink)
            for member in self.voice_channel.channel.members:
                self.last_packet_location[member] = 0
        
        await asyncio.sleep(time)
    
    
    async def transcribe_audio(self):
        """Transcribes the new audio packets for each user that was heard."""
        try:
            packets_to_process = self.sink.user_audio
            translator = str.maketrans('', '', string.punctuation)
            
            for member, packets in packets_to_process.items():
                if member not in self.last_packet_location:
                    self.last_packet_location[member] = 0
                
                packets = packets[-self.last_packet_location[member]:]
                self.last_packet_location[member] += len(packets)
                
                if len(packets) > 5:
                    cleaned_words = [word.translate(translator) for word in member.split()]
                    filename = ''.join(cleaned_words) + '.wav'
                    
                    packets.export(filename, format="wav")
                    self.audio_files[member] = filename
            
            for member, file in self.audio_files.items():
                with open(file, 'rb') as file:
                    self.transcription.append({member: openai.audio.transcriptions.create(
                        model="whisper-1",
                        file=file
                    ).text})
            
            self.log_handler.debug(f"The transcription that has been captured is as follows:\n{self.transcription}")
        except Exception as e:
            self.log_handler.error(f'Encountered an error when transcibing audio:\n{e}')
    
    
    async def cleanup(self):
        """Cleans up any leftover audio files."""
        try:
            for file in self.audio_files.values():
                os.remove(file)
            for file in os.listdir(self.sink.wave_folder):
                os.remove(os.join(self.sink.wave_folder, file))
                
        except Exception as e:
            self.log_handler.error(f'Encountered an error when cleaning up files:\n{e}')
    
    
    async def generate_voice_response(self):
        """Generates a text response to the current conversation that has been transcribed. Uses the stored history of previous generations as well."""
        try:
            instructions = self.bot_manager.text_handler.prompt + INSTRUCTION_PROMPT
            messages = [{"role": "system", "content": instructions}]
            
            for audio in self.transcription:
                for member, text in audio.items():
                    if member != self.bot_manager.name:
                        messages.append({"role": "user", "content": '{}: {}'.format(member, text)})
                    else:
                        messages.append({"role": "assistant", "content": text})
            
            self.log_handler.debug(f"The conversation the generate a response to is as follows:\n{messages}")
            
            response = await self.bot_manager.text_handler.generate(messages)
            self.transcription.append({self.bot_manager.name: response})
            
            self.log_handler.debug(f"Response is as follows:\n{response}")
            
            return response
        except Exception as e:
            self.log_handler.error(f'Encountered an exception when generating a text response:\n{e}')


    async def play_audio(self, response):
        """Creates and plays the audio response that has been provided.

        Args:
            response (str): A string that holds the generated text response the bot wishes to speak.
        """
        try:
            body = {'text': response,
                    'model_id': self.bot_manager.voice_model,
                    'voice_settings': {'stability': 0.15,
                                    'similarity_boost': 0.7,
                                    'style': 0.1,
                                    'use_speaker_boost': True
                                    }
                    }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url='https://api.elevenlabs.io/v1/text-to-speech/' + self.bot_manager.voice_handler.voice['voice_id'] + '/stream',
                                        headers={'XI-API-KEY': self.bot_manager.voice_handler.api_key,
                                                 'Content-Type': 'application/json'},
                                        json=body) as r:
                    content = io.BytesIO(await r.read())
                    self.voice_channel.play(StreamingAudio(content.read(), pipe=True))
            
            while self.voice_channel.is_playing():
                await asyncio.sleep(1)
                
        except Exception as e:
            self.log_handler.error(f'Encountered an exception when playing response:\n{e}')
    
    async def send_combined_audio(self, interaction:discord.Interaction):
        """Combines all of the final wav files and sends in response to the slash command invoked."""
        final_files = [os.path.join(self.sink.wave_folder, f) for f in os.listdir(self.sink.wave_folder)]
        combined_audio = AudioSegment.from_wav(final_files[0])
        
        for file in final_files[1:]:
            combined_audio = combined_audio.overlay(AudioSegment.from_wav(file))
        
        combined_audio.export(os.path.join(self.sink.wave_folder, 'final.wav'), format='wav')
        interaction.followup.send(file=discord.File(os.path.join(self.sink.wave_folder, 'final.wav')))
        
            
            
#? The custom discord.AudioSource that allows streaming audio from ElevenLabs into the discord.
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

class ContinuousWaveSink(voice_recv.AudioSink):
    def __init__(self, wave_folder=AUDIO_FILE_LOCATION, silence_threshold=0.02):
        """
        Custom sink to continuously record audio, handling silence periods.

        Args:
            wave_folder (str): Directory to save the .wav files.
            silence_threshold (float): Threshold in seconds to insert silence when no packets are received.
        """
        super().__init__()  # Ensure proper initialization of AudioSink
        
        self.wave_folder = wave_folder
        self.user_audio = {}  # Stores audio per user
        self.last_packet_time = {}  # Tracks last received packet timestamp
        self.silence_threshold = silence_threshold  # Silence insertion threshold

        # Ensure the destination folder exists
        os.makedirs(self.wave_folder, exist_ok=True)

    def wants_opus(self):
        """Override to return False since we are dealing with PCM audio."""
        return False

    def write(self, user, data: voice_recv.VoiceData):
        
        user = user.global_name
        current_time = time.time()

        # Convert raw PCM data to an AudioSegment
        audio_segment = AudioSegment(
            data.pcm,
            sample_width=2,
            frame_rate=44100,
            channels=2
        )

        if user not in self.user_audio:
            self.user_audio[user] = audio_segment
            self.last_packet_time[user] = current_time
        else:
            # Calculate time gap and insert silence if needed
            gap_duration = (current_time - self.last_packet_time[user])
            if gap_duration > self.silence_threshold:
                self.user_audio[user] += AudioSegment.silent(duration=gap_duration)

            self.user_audio[user] += audio_segment
            self.last_packet_time[user] = current_time

    def cleanup(self):
        """Saves each user's recorded audio to individual .wav files."""
        for user_id, audio in self.user_audio.items():
            output_path = os.path.join(self.wave_folder, f"{user_id}.wav")
            audio.export(output_path, format="wav")

        self.user_audio.clear()