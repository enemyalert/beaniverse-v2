import discord
from discord.ext import commands
import aiohttp
import tempfile
import os
from nudenet import NudeDetector
import logging
from typing import Optional, Tuple
import asyncio
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import io

logger = logging.getLogger(__name__)

class NSFWDetector:
    def __init__(self):
        self.detector = NudeDetector()
        
        self.executor = ThreadPoolExecutor(max_workers=2)
        
        self.NSFW_THRESHOLD = 0.7  
        self.ALLOWED_FORMATS = {
            'image': ['.jpg', '.jpeg', '.png', '.webp'],
            'video': ['.mp4', '.mov', '.webm']
        }

        self.session = aiohttp.ClientSession()

    async def download_file(self, url: str) -> Optional[str]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return None
                    
                    extension = os.path.splitext(url)[1].lower()
                    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp_file:
                        tmp_file.write(await response.read())
                        return tmp_file.name
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            return None

    def analyze_image(self, file_path: str) -> Tuple[bool, float]:
        try:
            result = self.detector.detect(file_path)

            if not result:
                return False, 0.0
            
            nsfw_score = max((pred['score'] for pred in result), default=0.0)
            return nsfw_score >= self.NSFW_THRESHOLD, nsfw_score
        except Exception as e:
            logger.error(f"Error analyzing image: {e}")
            return False, 0.0

    def analyze_video(self, file_path: str) -> Tuple[bool, float]:
        try:
            results = self.video_detector.detect_video(file_path)

            if not results:
                return False, 0.0
                
            nsfw_frames = sum(1 for frame in results if frame['score'] >= self.NSFW_THRESHOLD)
            nsfw_percentage = nsfw_frames / len(results)
            
            return nsfw_percentage >= 0.3, nsfw_percentage  
        except Exception as e:
            logger.error(f"Error analyzing video: {e}")
            return False, 0.0

    async def analyze_attachment(self, attachment: discord.Attachment) -> Tuple[bool, float, str]:
        file_ext = os.path.splitext(attachment.filename)[1].lower()
        
        if file_ext in self.ALLOWED_FORMATS['image']:
            content_type = 'image'
        elif file_ext in self.ALLOWED_FORMATS['video']:
            content_type = 'video'
        else:
            return False, 0.0, "Unsupported format"

        temp_path = await self.download_file(attachment.url)
        if not temp_path:
            return False, 0.0, "Download failed"

        try:
            if content_type == 'image':
                is_nsfw, score = await asyncio.get_event_loop().run_in_executor(
                    self.executor,
                    self.analyze_image,
                    temp_path
                )
            else:
                is_nsfw, score = await asyncio.get_event_loop().run_in_executor(
                    self.executor,
                    self.analyze_video,
                    temp_path
                )

            return is_nsfw, score, content_type
        finally:
            try:
                os.unlink(temp_path)
            except Exception as e:
                logger.error(f"Error deleting temp file: {e}")

    async def check_image(self, image_url: str) -> Tuple[bool, float, str]:
        try:
            async with self.session.get(image_url) as response:
                if response.status != 200:
                    logger.error(f"Failed to download image: {response.status}")
                    return False, 0.0, "unknown"

                image_data = await response.read()

                try:
                    img = Image.open(io.BytesIO(image_data))
                    img.verify()
                except Exception as e:
                    logger.error(f"Invalid image format: {e}")
                    return False, 0.0, "invalid"

                return False, 0.0, "safe"

        except Exception as e:
            logger.error(f"Error checking image: {e}")
            return False, 0.0, "error"

    async def check_message(self, message: discord.Message) -> Tuple[bool, float, str]:
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith('image/'):
                is_nsfw, score, content_type = await self.check_image(attachment.url)
                if is_nsfw:
                    return True, score, content_type
        return False, 0.0, "safe"

    def cleanup(self):
        self.executor.shutdown(wait=True)

        if not self.session.closed:
            self.session.close()
