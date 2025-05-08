from typing import Optional
from pydantic import BaseModel, Field, model_validator

class ClientId(BaseModel):
    client_id: str

class OnCompleted(BaseModel):
    callback_uri: str
    data: ClientId

class TranscriptionTaskData(BaseModel):
    """Data structure for transcription task information."""
    task_uuid: str = Field(..., description="Unique identifier for the transcription task")
    file_name: str = Field(..., description="Name of the file being transcribed")
    token: str = Field(..., description="Authentication token for for downloading the file")
    tokens: int = Field(..., description="Tokens consumed for transcription")
    download_url: str = Field(..., description="URL to download the file from")
    service: str = Field(..., description="Service used for transcription (e.g., 'whisper')")
    language: str = Field(..., description="Language code for transcription")
    model: str = Field(..., description="Model to use for transcription")
    embed_subtitles: bool = Field(..., description="Whether to embed subtitles in the output")
    test_mode: Optional[bool] = Field(None, description="Whether this is a test run")
    on_completed: OnCompleted = Field(..., description="Callback information when task completes")
    error: Optional[str] = Field(None, description="Error message if task failed")
    symlink: Optional[str] = Field(None, description="Symlink to the file")

    @model_validator(mode="before")
    def normalize_fields(cls, values):
        """Normalize field names and structure"""
        # Handle task_id vs task_uuid
        if 'task_id' in values and not values.get('task_uuid'):
            values['task_uuid'] = values['task_id']
            
        return values
    
    @property
    def callback_uri(self) -> Optional[str]:
        """Get callback URI safely from on_completed, regardless of its structure"""
        if not self.on_completed:
            return None
            
        if isinstance(self.on_completed, dict):
            return self.on_completed.get('callback_uri')
        
        return self.on_completed.callback_uri
    
    @property
    def client_id(self) -> Optional[str]:
        """Get client ID safely from on_completed, regardless of its structure"""
        if not self.on_completed:
            return None
            
        if isinstance(self.on_completed, dict):
            data = self.on_completed.get('data', {})
            if isinstance(data, dict):
                return data.get('client_id')
            return None
        
        if hasattr(self.on_completed, 'data') and hasattr(self.on_completed.data, 'client_id'):
            return self.on_completed.data.client_id
            
        return None
    
class StreamData(BaseModel):
    client_id: str = Field(..., description="Client ID")
    task_uuid: str = Field(..., description="Task UUID")
    file_id: str = Field(..., description="File ID")
    file_name: str = Field(..., description="File Name")
    source_file_name: str = Field(..., description="Source File Name")
    tokens: int = Field(..., description="Tokens")
    error: Optional[str] = Field(None, description="Error")
    symlink: Optional[str] = Field(None, description="Symlink to the file")
class StreamEventResponse(BaseModel):
    """Response from the stream event publishing."""
    entry_id: str = Field(..., description="ID of the published stream entry") 