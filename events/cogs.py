from pathlib import Path
import logging
from typing import Optional

class CogManager:
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('Beaniverse-v2')
        self.base_dir = Path(self.bot.__module__).resolve().parent

    async def load_cogs(self) -> int:
        """Load all cogs from the cogs directory"""
        try:
            
            cogs_dir = self.base_dir / 'cogs'
            
            self.logger.info(f'Looking for cogs in: {cogs_dir}')
            
            if not cogs_dir.exists():
                self.logger.error(f'Cogs directory not found at: {cogs_dir}')
                raise FileNotFoundError(f'Cogs directory not found at: {cogs_dir}')
            
            cog_count = 0
            for file in cogs_dir.glob('*.py'):
                if file.name != '__init__.py':
                    try:
                        await self.bot.load_extension(f'cogs.{file.stem}')
                        self.logger.info(f'Loaded cog: {file.stem}')
                        cog_count += 1
                    except Exception as e:
                        self.logger.error(f'Failed to load cog {file.stem}: {str(e)}')
            
            self.logger.info(f'Successfully loaded {cog_count} cogs')
            return cog_count
            
        except Exception as e:
            self.logger.error(f"Error loading cogs: {e}", exc_info=True)
            raise
