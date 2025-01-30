import os
import discord
import openai
import logging
from datetime import datetime

MAX_TOKENS = 128 # Setting token limit for ChatGPT responses
CHAT_MODEL = "gpt-4o-2024-08-06" # Model for OpenAI Completions to use

class OpenAIHandler:
    """Handles all text generation from OpenAI, as well as holding short term memory for all servers.

    Creates a new OpenAIHandler that communicates with OpenAI's API to generate realtime text responses.

    Attributes:
        _name: A string designating a name for the bot. This is used for handling the setup of grabbing the bot's logger.
        _status_messages: A dictionary of strings that are used for logging and sending various status messages for unique situations.
        _prompt: A string that is used in the \'assistant\' section when sending an API call to OpenAI.
    """
    
    def __init__(self, _name, _status_messages: dict, _prompt: str):
        """Inits OpenAIHandler using bot details and assigned prompt."""
        self.name = _name
        openai.api_key = os.getenv('CHATGPT_TOKEN')
        self.memory = {}
        self.last_interaction = {}
        self.log_handler = logging.getLogger(self.name)
        self.status_messages = _status_messages
        self.prompt = _prompt

    async def show_prompt(self, interaction: discord.Interaction):
        """Returns response to user that contains the prompt used with OpenAI."""
        await interaction.response.send_message("Here is the prompt used. Feel free to use this to use with ChatGPT on your own:\n\n{}".format(self.prompt), ephemeral=True)

    async def reset(self, interaction: discord.Interaction):
        """Resets the context memory for the server that the command was invoked in."""
        self.memory[interaction.guild.id].clear()
        self.memory[interaction.guild.id].append({"role": "system", "content": self.prompt})
        
        await interaction.response.send_message('{}'.format(self.status_messages['reset'].replace('{USERNAME}', interaction.user.display_name)))
    
    async def generate(self, message: str, temp: float, freq_penalty: float, presence_penalty: float):
        """Returns the contents of an OpenAI API call in response to a user message.

        Args:
            message (str): The message or content to generate a response to.
            temp (float): The randomness of the output.
            freq_penalty (float): How likely the reponse is to repeat words or phrases.
            presence_penalty (float): How likely to introduce new topics to the conversation.

        Returns:
            str: The response obtained, returns as a string.
        """
        completion = openai.chat.completions.create(
            model=CHAT_MODEL,
            messages=message,
            max_tokens=MAX_TOKENS,
            temperature=temp,
            frequency_penalty=freq_penalty,
            presence_penalty=presence_penalty
        )
        return completion.choices[0].message.content

    async def chat(self, interaction: discord.Interaction, prompt: str, temperature: float, frequency_penalty: float, presence_penalty: float):
        """Takes in a user input and generates a response. Other recent /chat commands are included as well.

        Args:
            interaction (discord.Interaction): The reference to the invoked slash command.
            prompt (str): The user prompt that a response is needed from.
            temperature (float): The randomness of the output.
            frequency_penalty (float): How likely the response is to repeat words or phrases.
            presence_penalty (float): How likely to introduce new topics to the conversation.
        """
        await interaction.response.defer()
        
        try:
            self.memory[interaction.guild.id].append({"role": "user", "content": prompt})
            completion = await self.generate(self.memory[interaction.guild.id], temperature, frequency_penalty, presence_penalty)
            self.log_handler.info(f'Generated response to the /chat request:\n{completion}')
            
            if completion.usage.total_tokens > 500:
                removed_user = self.memory[interaction.guild.id].pop(1)
                removed_assistant = self.memory[interaction.guild.id].pop(1)
                self.log_handler.warning(f'Memory token limit reached. Removed the user prompt and accomponying response: {removed_user}\n{removed_assistant}')
            
            self.memory[interaction.guild.id].append({"role": "assistant", "content": completion.choices[0].message.content})
            await interaction.followup.send('{} *"{}"* \n\n{}'.format(self.status_messages['chat']['response'].replace('{USERNAME}', interaction.user.display_name),
                                                                                                           prompt,
                                                                                                           completion.choices[0].message.content))
            self.last_interaction[interaction.guild.id] = datetime.now()
        except Exception as e:
            self.log_handler.error(f'Error in /chat command:{e}')
            await interaction.followup.send("{} (Something went wrong)".format(self.status_messages['chat']['error']))
    
    async def setup_memory(self, guilds: list):
        """Sets up the memory for all servers the bot is in.

        Args:
            guilds (list): The list of servers that memory should be created for.
        """
        for server in guilds:
            self.log_handler.debug(f'Setting up context memory for server: {server.id} ({server.name})')
            self.memory[server.id] = [{"role": "system", "content": self.prompt}]
            self.last_interaction[server.id] = datetime.now()
    
    async def reset_memory(self, guilds: list, currentTime: datetime):
        """Resets the memory if enough time has passed.

        Args:
            guilds (list): List of servers that the bot is in.
            currentTime (datetime): The current time that the function was called at.
        """
        for server in guilds:
            time_diff = currentTime - self.last_interaction[server.id]
            if time_diff.days > 0 or (time_diff.seconds / 3600) >= 3:
                self.log_handler.debug(f'Resetting chat memory for server due to inactivity: {server.id} ({server.name})')
                self.memory[server.id] = [{"role": "system", "content": self.prompt}]
                self.last_interaction[server.id] = datetime.now()