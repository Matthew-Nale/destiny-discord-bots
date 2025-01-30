import requests as re
import aiohttp
import logging
import discord
import asyncio

ELEVEN_BASE_URL = 'https://api.elevenlabs.io'
MAX_LEN = 1024 # Setting character limit for ElevenLabs

class ElevenLabsHandler:
    """Handles all voice and audio generation from ElevenLabs.

    Creates a new ElevenLabsHandler that communicates with ElevenLabs's API to generate new audio.

    Attributes:
        _name: A string designating a name for the bot. This is used for handling the setup of grabbing the bot's logger.
        _api_key: The ElevenLabs API Key that holds the cloned voice for the bot.
        _voice_name: The name of the voice to generate audio as.
    """
    def __init__(self, _name:str, _api_key:str, _voice_name:str):
        """Inits ElevenLabsHandler using bot details and the required ElevenLabs information."""
        self.name = _name
        self.api_key = _api_key
        self.voice_name = _voice_name
        
        self.log_handler = logging.getLogger(self.name)
        request = re.get(url=ELEVEN_BASE_URL + '/v1/voices', headers={'XI-API-KEY':self.api_key})
        name_check = [d for d in request.json()['voices'] if d['name'] == self.voice_name]
        if name_check:
            self.voice = name_check[0]
    
    async def credits(self, interaction: discord.Interaction) -> (None):
        """Returns response to user that shows the remaining credits available for generating audio.

        Args:
            interaction (discord.Interaction): The reference to the invoked slash command.
        """
        
        async with aiohttp.ClientSession() as session:
            async with session.get(ELEVEN_BASE_URL + '/v1/user/subscription', headers={'XI-API-KEY': self.api_key}) as r:
                user = await r.json()
        char_remaining = user['character_limit'] - user['character_count']
        
        if char_remaining:
            await interaction.response.send_message(f'I will still speak {char_remaining} characters. Use them wisely.', ephemeral=True)
        else:
            await interaction.response.send_message('{} (Reached character quota for this month)'.format(self.status_messages['credits']))

        
    async def generate(self, text: str, model: str='eleven_monolingual_v1', stability: float=0.5, 
                       similarity_boost: float=0.75, style: float=0, use_speaker_boost: bool=False) -> bytes:
        """Generates audio from communication with the ElevenLabs API.

        Args:
            text (str): The text that is to be used to create the audio.
            model (str, optional): The audio model that the voice should use. Defaults to 'eleven_monolingual_v1'.
            stability (float, optional): How stable the generated audio should be. Defaults to 0.5.
            similarity_boost (float, optional): How similar to the training audio the generated audio should be. Defaults to 0.75.
            style (float, optional): How exaggerated the generated audio should be. Defaults to 0.
            use_speaker_boost (bool, optional): Whether to enable speaker boost or not. Defaults to False.

        Returns:
            bytes: Bytes that holds the generated audio data.
        """
        if len(text) > MAX_LEN:
            self.log_handler.warning(f'Size of request was too long for /speak\n\n')
            return -1
        
        body = {'text': text,
                'model_id': model,
                'voice_settings': {'stability': stability,
                                   'similarity_boost': similarity_boost,
                                   'style': style,
                                   'use_speaker_boost': use_speaker_boost
                                   }
                }
        async with aiohttp.ClientSession() as session:
            async with session.post(url=ELEVEN_BASE_URL + '/v1/text-to-speech/' + self.voice['voice_id'] + '?optimize_streaming_latency=0',
                                    headers={'XI-API-KEY': self.api_key},
                                    json=body) as r:
                request = await r.read()
        return request

    async def speak_in_vc(self, channel: discord.VoiceChannel, audio: str):
        """Play an audio clip in a voice channel.

        Args:
            channel (discord.VoiceChannel): The voice channel to connect to and play audio in.
            audio (str): The filename of the audio file to play in the voice channel.
        """
        
        try:
            vc = await channel.connect()
            await asyncio.sleep(0.75)
            vc.play(discord.FFmpegPCMAudio(source=audio))
            while vc.is_playing():
                await asyncio.sleep(0.75)
            vc.stop()
        except Exception as e:
            self.log_handler.error(f"Error happened while joining VC to play audio: {e}")
            
        await vc.disconnect()