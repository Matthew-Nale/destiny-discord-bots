import os
import discord
import asyncio
import string
import logging
import json
import random
import datetime

MAX_TOKENS = 128 # Setting token limit for ChatGPT responses
CHAT_MODEL = "gpt-4o-2024-08-06" # Model for OpenAI Completions to use
TALK_CHANCE = 0.05

from discord import app_commands, Message
from discord.ext import commands, tasks
from log_handler import create_logger
from voice_handler import ElevenLabsHandler
from text_handler import OpenAIHandler



class BotManager(commands.Bot):
    """Handles all actions related to bot commands or attributes.

    Creates a modified discord.commands.Bot object with generic text commands already setup.
    The newly created bot instance must be ran using asyncio.run(self.start(self.discord_token)).
    
    To add commands related to voice, use the add_voice_commands(voice_key: str) command after creation.
    To add random events that the bot can autonomously perform, use the setup_random_events() command.

    Attributes:
        _name: A string designating a name for the bot. This is used for handling logging, as well as pulling character data.
        _discord_token: A string that holds the discord API token supplied for the bot, used on startup of the bot.
    """
    
    def __init__(self, _name:str, _discord_token:str):
        """Inits BotManager with the name and discord token associated with the Discord bot."""
        super().__init__(command_prefix=commands.when_mentioned_or('!{self.name}'), intents=discord.Intents.all())
        self.name = _name
        self.discord_token = _discord_token
        
        self.log_handler = create_logger(self.name, logging.getLogger('main'))
        
        with open('../data/character_data.json', 'r') as file:
            character_data = json.load(file)
            
        self.text_handler = OpenAIHandler(
            self.name, 
            character_data[self.name]['status_messages']['text'], 
            character_data[self.name]['chat_prompt']
        )
        
        self.add_text_commands()
    

    async def on_ready(self):
        """Syncs all commands registered, and setups memory cleaning for text conversations on startup."""
        self.log_handler.debug(f"{self.user} has connected to Discord!")
    
        try:
            synced = await self.tree.sync()
            self.log_handler.debug(f"Synced {len(synced)} commands for all servers.")
        except Exception as e:
            self.log_handler.critical(f"Error syncing commands: {e}")
        
        await self.text_handler.setup_memory(self.guilds)
        await self.cleanMemories.start()
    
    @tasks.loop(hours = 3)
    async def cleanMemories(self):
        """Task to clean unused text memory from each server."""
        await self.text_handler.reset_memory(self.guilds, datetime.datetime.now())
    
    def setup_random_events(self, talk_chance: float):
        """Setups various autonomous replies and interactions.
        
        Args:
            talk_chance (float): The chance for all random chances when talking through text or voice.
        """
        self.log_handler.debug(f'Adding RandomEvents cog to the bot.')
        asyncio.run(self.add_cog(RandomEvents(self, talk_chance)))
    
    def add_text_commands(self):
        """Adds all generic text commands to the bot."""
        
        @self.tree.command(name=f"{self.name.lower()}_prompt", description="Show the prompt that is used to prime the /chat command.")
        async def prompt(interaction: discord.Interaction):
            """Informs the text_handler to reply with the system prompt used when generating text responses."""
            self.log_handler.info(f'{interaction.user.global_name} asked for the ChatGPT Prompt.')
            await self.text_handler.show_prompt(interaction)

        @self.tree.command(name=f"{self.name.lower()}_reset", description="Reset the /chat memory in case anything gets incoherent.")
        async def reset(interaction: discord.Interaction):
            """Informs the text_handler to reset the context memory for the channel the message was received in."""
            self.log_handler.info(f'{interaction.user.global_name} cleared the memory.')
            await self.text_handler.reset(interaction)
        
        @self.tree.command(name=f"{self.name.lower()}_chat", description= "Ask me anything you want!")
        @app_commands.describe(prompt="What would you like to ask me?",
                               temperature="How random should the response be? Range between 0.0:2.0, default is 1.2.",
                               frequency_penalty="How likely to repeat the same line? Range between -2.0:2.0, default is 0.9.",
                               presence_penalty="How likely to introduce new topics? Range between -2.0:2.0, default is 0.75.")
        async def chat(interaction: discord.Interaction, prompt: str, temperature: float=1.2, frequency_penalty: float=0.9, presence_penalty: float=0.75):
            """Communicates with the text_handler to generate a unique response to a user supplied message."""
            self.log_handler.info(f'{interaction.user.global_name} asked for a /chat response to the following prompt: \n\"{prompt}\"')
            await self.text_handler.chat(interaction, prompt, temperature, frequency_penalty, presence_penalty)
    
    def add_voice_commands(self, voice_key: str):
        """Adds all generic voice commands to the bot.

        Args:
            voice_key (str): ElevenLabs API key that hosts the cloned voice.
        """
        DEFAULT_VC = os.getenv('DEFAULT_VOICE_CHANNEL_ID')
        with open('../data/character_data.json', 'r') as file:
            character_data = json.load(file)
            
        self.voice_model = character_data[self.name]['voice_model']
        self.voice_name = character_data[self.name]['voice_name']
        self.voice_errors = character_data[self.name]['status_messages']['voice']
        
        self.log_handler.debug(f'Creating new voice handler.')
        self.voice_handler = ElevenLabsHandler(self.name, voice_key, self.voice_name)
        self.log_handler.debug(f'Voice handler has been successfully created.')
        
        @self.tree.command(name=f"{self.name.lower()}_credits", description="Shows the credits remaining for ElevenLabs.")
        async def credits(interaction: discord.Interaction):
            """Informs the voice_handler to reply with the remaining credits available for generating speech."""
            self.log_handler.info(f'{interaction.user.global_name} asked for the remaining credits.')
            await self.voice_handler.credits(interaction)
        
        @self.tree.command(name=f"{self.name.lower()}_speak", description="Text-to-speech to read out some text, and say it in the VC you are connected to if joinable!")
        @app_commands.describe(text="What should I say in the VC?",
                       stability="(Optional) How expressive should it be said? Float from 0-1.0, default is 0.5",
                       clarity="(Optional) How similar to the in-game voice should it be? Float from 0-1.0, default is 0.8",
                       style="(Optional) How exaggerated should the text be read? Float from 0-1.0, default is 0.1")
        async def speak(interaction: discord.Interaction, text: str, stability: float=0.2, clarity: float=0.7, style: float=0.1) -> (None):
            """Communicates with the voice_handler to generate audio of a supplied message.\n
            The bot will attempt to speak in a valid VC, but will always send the audio file afterwords."""
            self.log_handler.info(f'{interaction.user.global_name} asked {self.name} to say: `{text}`')
            await interaction.response.defer()

            self.log_handler.debug(f'Checking for any Valid VC to join.')
            channel = interaction.user.voice.channel if interaction.user.voice else self.bot.get_channel(DEFAULT_VC)
            
            self.log_handler.debug(f'Attempting to generate audio for the /speak command.')
            try:
                audio = await self.voice_handler.generate(
                    text=text,
                    model=self.voice_model,
                    stability=stability,
                    similarity_boost=clarity,
                    style=style,
                    use_speaker_boost=True
                )
                
                if audio == -1:
                    self.log_handler.warning(f'Cancelling audio request due to length.')
                    await interaction.followup.send("{} (Text too long)".format(self.voice_errors['too_long']), ephemeral=True)
                    return
                
                split_text = text.split()
                if len(split_text) < 5:
                    filename = f'{split_text[0]}.mp3'
                else:
                    translator = str.maketrans('', '', string.punctuation)
                    cleaned_words = [word.translate(translator) for word in split_text]
                    filename = f'{cleaned_words[0]}_{cleaned_words[1]}_{cleaned_words[2]}_{cleaned_words[3]}_{cleaned_words[4]}.mp3'
                    
                with open(filename, "wb") as f:
                    f.write(audio)
                self.log_handler.debug(f'Generated audio for the /speak command. Saved as {filename}')
                
                self.log_handler.debug(f'Attempting to speak in VC.')
                await self.voice_handler.speak_in_vc(channel, filename)
                
                await interaction.followup.send(file=discord.File(filename))
                self.log_handler.info(f'Finished processing speak command. Sent .mp3 titled `{filename}`.')
                os.remove(filename)
            except Exception as e:
                self.log_handler.error(f'Error in /speak:\n{e}')
                await interaction.followup.send("{} (Something went wrong with that request)".format(self.voice_errors['error']),
                                            ephemeral=True)
        

class RandomEvents(commands.Cog):
    """Handles all generic timed and random events.

    Creates a new discord.commands.Cog object to handle all listeners and autonomous events.
    To be added to the bot, it must be setup by using the default Discord.py add_cog() command

    Attributes:
        _bot: The BotManager object that is wanting to add the Cog. Used tto handle all text and audio operations.
        _talk_chance: A float that determines the chance that the bot responds to a text message or joins active voice channels.
    """
    def __init__(self, _bot: BotManager, _talk_chance: float):
        """Inits RandomEvents with the BotManager and talk chance."""
        self.bot_manager = _bot
        self.log_handler = logging.getLogger(self.bot_manager.name)
        self.talk_chance = _talk_chance

    @commands.Cog.listener("on_message")
    async def on_message(self, message: Message):
        """Listens to all text messages seen to potentially respond to one.

        Args:
            message (discord.Message): The message that was received in a valid text channel.
        """
        if not message.attachments:
            if random.random() <= self.talk_chance:
                self.log_handler.info(f"A message in the channel \'{message.channel.name}\' triggered an automatic response.")
                past_messages = [m async for m in message.channel.history(after=datetime.datetime.now() - datetime.timedelta(hours=12), limit=5, oldest_first=False)]
                past_messages.reverse()
                response = await self.generate_response(past_messages)
                self.log_handler.info(f'Chiming-in on previous messages {[msg.content for msg in past_messages]} with bot: {self.bot_manager.name}. Response: {response}')
                await self.bot_manager.get_channel(message.channel.id).send(response, reference=message)
        await self.bot_manager.process_commands(message)

    async def generate_response(self, user_msgs: list):
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


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    RHULK_TOKEN = os.getenv('DISCORD_TOKEN_RHULK')
    test = BotManager("Rhulk", RHULK_TOKEN)
    VOICE_KEY = os.getenv('ELEVEN_VOICE_KEY')
    test.add_voice_commands(VOICE_KEY)
    test.setup_random_events(TALK_CHANCE)
    test.log_handler.info(f'Created a new bot manager with the name {test.name}')
    asyncio.run(test.start(test.discord_token))
