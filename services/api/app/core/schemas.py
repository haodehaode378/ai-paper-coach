from pydantic import BaseModel, ConfigDict, Field


class ProviderConfig(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout_sec: int | None = None


class ModelConfig(BaseModel):
    # Generic slots (recommended)
    primary: ProviderConfig | None = None
    secondary: ProviderConfig | None = None
    provider_a: ProviderConfig | None = None
    provider_b: ProviderConfig | None = None

    # Backward compatibility
    qwen: ProviderConfig | None = None
    minimax: ProviderConfig | None = None


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    paper_id: str
    mode: str = Field(default="deep")
    llm_config: ModelConfig | None = Field(default=None, alias="model_config")


class ReviewRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    paper_id: str
    llm_config: ModelConfig | None = Field(default=None, alias="model_config")


class FinalizeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    paper_id: str
    strict: bool = False
    llm_config: ModelConfig | None = Field(default=None, alias="model_config")


class ValidateModelsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    llm_config: ModelConfig | None = Field(default=None, alias="model_config")


class IngestJSONRequest(BaseModel):
    url: str
