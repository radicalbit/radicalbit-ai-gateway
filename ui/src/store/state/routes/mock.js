const getAllRoutes = [
  {
    routeName: 'customer-service',
    configuration: {
      routeName: 'customer-service',
      chatModels: [
        {
          modelId: 'qwen',
          model: 'openai/qwen2.5:3b',
          credentials: {
            apiKey: '**********',
            baseUrl: 'http://host.docker.internal:11434/v1',
          },
          params: {
            temperature: 0.7,
            topP: 0.9,
          },
          retryAttempts: 3,
        },
        {
          modelId: 'llama3.2',
          model: 'openai/llama3.2',
          credentials: {
            apiKey: '**********',
            baseUrl: 'http://host.docker.internal:11434/v1',
          },
          params: {
            temperature: 0.7,
            topP: 0.9,
          },
          retryAttempts: 3,
        },
        {
          modelId: 'openai-4o',
          model: 'openai/gpt-4o',
          credentials: {
            apiKey: '**********',
          },
          params: {
            temperature: 1,
            maxTokens: 20,
          },
          retryAttempts: 3,
          inputCostPerMillionTokens: 2.5,
          outputCostPerMillionTokens: 10.0,
          inputCostPerToken: 2.5e-06,
          outputCostPerToken: 1e-05,
        },
      ],
      embeddingModels: [
        {
          modelId: 'text-embedding-3-small',
          model: 'openai/text-embedding-3-small',
          credentials: {
            apiKey: '**********',
          },
          retryAttempts: 3,
          inputCostPerMillionTokens: 0.02,
          inputCostPerToken: 2e-08,
        },
        {
          modelId: 'text-embedding-ada-002',
          model: 'openai/text-embedding-ada-002',
          credentials: {
            apiKey: '**********',
          },
          retryAttempts: 3,
          inputCostPerMillionTokens: 0.09999999999999999,
          inputCostPerToken: 1e-07,
        },
      ],
      rateLimiting: {
        algorithm: 'FIXED_WINDOW',
        windowSize: '30 seconds',
        maxRequests: 20,
      },
      fallback: [
        {
          target: 'qwen',
          fallbacks: [
            'llama3.2',
          ],
          type: 'CHAT',
        },
        {
          target: 'llama3.2',
          fallbacks: [
            'qwen',
          ],
          type: 'CHAT',
        },
        {
          target: 'openai-4o',
          fallbacks: [
            'qwen',
          ],
          type: 'CHAT',
        },
        {
          target: 'text-embedding-3-small',
          fallbacks: [
            'text-embedding-ada-002',
          ],
          type: 'EMBEDDING',
        },
      ],
      guardrails: [
        {
          name: 'presidio_anonymizer',
          type: 'PRESIDIO_ANONYMIZER',
          description: 'Anonymize IBAN and emails codes',
          where: 'IO',
          behavior: 'WARN',
          parameters: {
            type: 'REDACT',
            language: 'it',
            entities: [
              'IBAN_CODE',
            ],
          },
          enabled: true,
        },
        {
          name: 'presidio_analyzer',
          type: 'PRESIDIO_ANALYZER',
          description: 'Block italian Identity card',
          where: 'INPUT',
          behavior: 'BLOCK',
          parameters: {
            type: 'REDACT',
            language: 'it',
            entities: [
              'IT_IDENTITY_CARD',
            ],
          },
          responseMessage: 'Identity card detected and blocked.',
          enabled: true,
        },
        {
          name: 'uuid_block',
          type: 'REGEX',
          where: 'INPUT',
          behavior: 'BLOCK',
          parameters: {
            type: 'CHECK',
            values: [
              '\\b[0-9a-f]{8}-[0-9a-f]{4}-[0-5][0-9a-f]{3}-[089ab][0-9a-f]{3}-[0-9a-f]{12}\\b',
            ],
            ignore_case: false,
          },
          responseMessage: 'Specific UUID format detected and blocked.',
          enabled: true,
        },
        {
          name: 'soft_block_email',
          type: 'PRESIDIO_ANALYZER',
          description: 'Soft block email',
          where: 'INPUT',
          behavior: 'SOFT_BLOCK',
          parameters: {
            type: 'REDACT',
            language: 'it',
            entities: [
              'EMAIL_ADDRESS',
            ],
          },
          responseMessage: 'This request is soft blocked so the answer is a natural language message of blocked content',
          enabled: true,
        },
      ],
    },
    metrics: {
      rateLimitTriggered: 86,
      inputCost: 0.0,
      outputCost: 0.0,
      fallbacks: {
        value: 12300,
        lastEvent:
        {
          routeName: 'marketing',
          target: 'model-A',
          fallback: 'model-B',
          timestamp: '2025-10-14 12:58:00',
          apiKeyName: 'dev-team',
          apiKeyUuid: 'fbaa0880-1795-4d70-b073-cc92fc4498b7',
        },
      },
      guardrails: {
        value: 120,
        lastEvent:
        {
          routeName: 'marketing',
          name: 'Presidio',
          where: 'INPUT',
          type: 'PRESIDIO_ANALYZER',
          behavior: 'BLOCK',
          timestamp: '2025-10-14 12:58:00',
          apiKeyName: 'dev-team',
          apiKeyUuid: 'fbaa0880-1795-4d70-b073-cc92fc4498b7',
        },
      },
      totalInputTokenProcessed: 2019,
      totalOutputTokenProcessed: 7243,
      totalCost: 0.0,
    },
    groups: [
      {
        uuid: 'f3825543-6299-4dc5-ad2f-2324da25d2c8',
        name: 'first-group',
        createdAt: '2025-10-15 12:55:31.549183+00:00',
        updatedAt: '2025-10-15 12:55:31.549183+00:00',
      },
    ],
  },
  {
    routeName: 'business-development',
    configuration: {
      routeName: 'business-development',
      chatModels: [
        {
          modelId: 'qwen',
          model: 'openai/qwen2.5:3b',
          credentials: {
            apiKey: '**********',
            baseUrl: 'http://host.docker.internal:11434/v1',
          },
          retryAttempts: 3,
        },
      ],
      rateLimiting: {
        algorithm: 'FIXED_WINDOW',
        windowSize: '20 seconds',
        maxRequests: 2,
      },
      tokenLimiting: {
        input: {
          algorithm: 'FIXED_WINDOW',
          windowSize: '10 seconds',
          maxToken: 5,
        },
        output: {
          algorithm: 'FIXED_WINDOW',
          windowSize: '10 minutes',
          maxToken: 500,
        },
      },
      fallback: [],
      guardrails: [],
    },
    metrics: {
      rateLimitTriggered: 0,
      tokenInputLimitTriggered: 0,
      tokenOutputLimitTriggered: 0,
      inputCost: 0.0,
      outputCost: 0.0,
      totalInputTokenProcessed: 0,
      totalOutputTokenProcessed: 0,
      totalCost: 0.0,
    },
    groups: [
      {
        uuid: '4c09c80c-cb33-4efa-8ef4-58560bedee56',
        name: 'second-group',
        createdAt: '2025-10-17 09:01:37.957521+00:00',
        updatedAt: '2025-10-17 09:01:37.957521+00:00',
      },
    ],
  },
  {
    routeName: 'marketing',
    configuration: {
      routeName: 'marketing',
      chatModels: [
        {
          modelId: 'qwen',
          model: 'openai/qwen2.5:3b',
          credentials: {
            apiKey: '**********',
            baseUrl: 'http://host.docker.internal:11434/v1',
          },
          retryAttempts: 3,
          inputCostPerMillionTokens: 0.25,
          outputCostPerMillionTokens: 0.025,
          inputCostPerToken: 2.5e-07,
          outputCostPerToken: 2.5000000000000002e-08,
        },
        {
          modelId: 'openai-4o',
          model: 'openai/gpt-4o',
          credentials: {
            apiKey: '**********',
          },
          retryAttempts: 3,
          inputCostPerMillionTokens: 2.5,
          outputCostPerMillionTokens: 10.0,
          inputCostPerToken: 2.5e-06,
          outputCostPerToken: 1e-05,
        },
      ],
      rateLimiting: {
        algorithm: 'FIXED_WINDOW',
        windowSize: '30 seconds',
        maxRequests: 120,
      },
      fallback: [
        {
          target: 'openai-4o',
          fallbacks: [
            'qwen',
          ],
          type: 'CHAT',
        },
      ],
      guardrails: [
        {
          name: 'presidio_anonymizer',
          type: 'PRESIDIO_ANONYMIZER',
          description: 'Anonymize IBAN and emails codes',
          where: 'IO',
          behavior: 'WARN',
          parameters: {
            type: 'REDACT',
            language: 'it',
            entities: [
              'IBAN_CODE',
            ],
          },
          enabled: true,
        },
        {
          name: 'presidio_analyzer',
          type: 'PRESIDIO_ANALYZER',
          description: 'Block italian Identity card',
          where: 'INPUT',
          behavior: 'BLOCK',
          parameters: {
            type: 'REDACT',
            language: 'it',
            entities: [
              'IT_IDENTITY_CARD',
            ],
          },
          responseMessage: 'Identity card detected and blocked.',
          enabled: true,
        },
      ],
      caching: {
        enabled: true,
        type: 'exact',
        ttl: 40,
      },
    },
    metrics: {
      rateLimitTriggered: 0,
      cacheTriggered: 99,
      cacheSavedTokensInput: 1584,
      cacheSavedTokensOutput: 891,
      savedAmountInput: 0.00396,
      savedAmountOutput: 0.008910000000000001,
      inputCost: 4e-05,
      outputCost: 9e-05,
      fallbacks: {
        value: 12300,
        lastEvent:
        {
          routeName: 'marketing',
          target: 'model-A',
          fallback: 'model-B',
          timestamp: '2025-10-14 12:58:00',
          apiKeyName: 'dev-team',
          apiKeyUuid: 'fbaa0880-1795-4d70-b073-cc92fc4498b7',
        },
      },
      guardrails: {
        value: 120,
        lastEvent:
        {
          routeName: 'marketing',
          name: 'Presidio',
          where: 'INPUT',
          type: 'PRESIDIO_ANALYZER',
          behavior: 'BLOCK',
          timestamp: '2025-10-14 12:58:00',
          apiKeyName: 'dev-team',
          apiKeyUuid: 'fbaa0880-1795-4d70-b073-cc92fc4498b7',
        },
      },
      totalInputTokenProcessed: 16,
      totalOutputTokenProcessed: 9,
      totalCachedTokens: 2475,
      totalSavedAmount: 0.012870000000000001,
      totalCost: 0.00013000000000000002,
    },
    groups: [
      {
        uuid: 'f3825543-6299-4dc5-ad2f-2324da25d2c8',
        name: 'first-group',
        createdAt: '2025-10-15 12:55:31.549183+00:00',
        updatedAt: '2025-10-15 12:55:31.549183+00:00',
      },
    ],
  },
  {
    routeName: 'finance',
    configuration: {
      routeName: 'finance',
      chatModels: [
        {
          modelId: 'llama3',
          model: 'openai/llama3.2:3b',
          credentials: {
            apiKey: '**********',
            baseUrl: 'http://host.docker.internal:11434/v1',
          },
          params: {
            temperature: 0.7,
            topP: 0.9,
          },
          retryAttempts: 3,
        },
      ],
      fallback: [],
      guardrails: [
        {
          name: 'contains_check_ponzi',
          type: 'CONTAINS',
          description: 'Check words inside the output text',
          where: 'OUTPUT',
          behavior: 'BLOCK',
          parameters: {
            type: 'CHECK',
            values: [
              'ponzi',
            ],
            ignore_case: false,
          },
          enabled: true,
        },
      ],
      caching: {
        enabled: true,
        type: 'exact',
        ttl: 300,
      },
    },
    metrics: {
      cacheTriggered: 0,
      cacheSavedTokensInput: 0,
      cacheSavedTokensOutput: 0,
      savedAmountInput: 0.0,
      savedAmountOutput: 0.0,
      inputCost: 0.0,
      outputCost: 0.0,
      guardrails: {
        value: 120,
        lastEvent:
        {
          routeName: 'marketing',
          name: 'Presidio',
          where: 'INPUT',
          type: 'PRESIDIO_ANALYZER',
          behavior: 'BLOCK',
          timestamp: '2025-10-14 12:58:00',
          apiKeyName: 'dev-team',
          apiKeyUuid: 'fbaa0880-1795-4d70-b073-cc92fc4498b7',
        },
      },
      totalInputTokenProcessed: 0,
      totalOutputTokenProcessed: 0,
      totalCachedTokens: 0,
      totalSavedAmount: 0.0,
      totalCost: 0.0,
    },
    groups: [
      {
        uuid: 'cc62fdd1-2fa8-48cc-af88-3f1c60708a06',
        name: 'foo',
        createdAt: '2025-10-20 07:10:54.075381+00:00',
        updatedAt: '2025-10-20 07:10:54.075381+00:00',
      },
    ],
  },
  {
    routeName: 'llm-judge-demo',
    configuration: {
      routeName: 'llm-judge-demo',
      chatModels: [
        {
          modelId: 'gpt-4o-mini',
          model: 'openai/gpt-4o-mini',
          credentials: {
            apiKey: '**********',
          },
          params: {
            temperature: 0.7,
            maxTokens: 500,
          },
          retryAttempts: 3,
          inputCostPerMillionTokens: 0.15,
          outputCostPerMillionTokens: 0.6,
          inputCostPerToken: 1.5e-07,
          outputCostPerToken: 6e-07,
        },
        {
          modelId: 'gpt-3.5-turbo',
          model: 'openai/gpt-3.5-turbo',
          credentials: {
            apiKey: '**********',
          },
          params: {
            temperature: 0.3,
            maxTokens: 300,
          },
          retryAttempts: 3,
          inputCostPerMillionTokens: 1.5,
          outputCostPerMillionTokens: 2.0,
          inputCostPerToken: 1.5e-06,
          outputCostPerToken: 2e-06,
        },
      ],
      rateLimiting: {
        algorithm: 'FIXED_WINDOW',
        windowSize: '60 seconds',
        maxRequests: 10,
      },
      fallback: [],
      guardrails: [
        {
          name: 'toxicity_judge',
          type: 'JUDGE',
          description: 'In-depth toxic content evaluation using LLM judge',
          where: 'INPUT',
          behavior: 'SOFT_BLOCK',
          parameters: {
            type: 'JUDGE',
            judgeConfig: {
              promptRef: 'toxicity_check.md',
              modelId: 'gpt-3.5-turbo',
              credentials: {
                apiKey: '**********',
              },
              temperature: 0.7,
              maxTokens: 100,
              requirePass: true,
              fallbackDurationSeconds: 60,
            },
          },
          responseMessage: '🚨 BLOCKED - Toxic content detected.',
          onTrigger: {
            degrade: {
              temperature: 0.2,
              maxTokens: 200,
              durationSeconds: 60,
            },
          },
          enabled: true,
        },
        {
          name: 'business_context_judge',
          type: 'JUDGE',
          description: 'Validate business context and intent using LLM judge',
          where: 'INPUT',
          behavior: 'BLOCK',
          parameters: {
            type: 'JUDGE',
            judgeConfig: {
              promptRef: 'business_context_check.md',
              modelId: 'gpt-3.5-turbo',
              credentials: {
                apiKey: '**********',
              },
              temperature: 0.7,
              maxTokens: 150,
              requirePass: true,
              fallbackDurationSeconds: 60,
            },
          },
          responseMessage: '🚨 BLOCKED - Request not aligned with business context.',
          enabled: true,
        },
        {
          name: 'prompt_injection_classifier',
          type: 'CLASSIFIER',
          description: 'Lightweight prompt injection detection using LLM classifier',
          where: 'INPUT',
          behavior: 'SOFT_BLOCK',
          parameters: {
            type: 'JUDGE',
            judgeConfig: {
              promptRef: 'prompt_injection_check.md',
              modelId: 'gpt-3.5-turbo',
              credentials: {
                apiKey: '**********',
              },
              temperature: 0.7,
              maxTokens: 50,
              threshold: 0.1,
              requirePass: true,
              fallbackDurationSeconds: 60,
            },
          },
          responseMessage: '🚨 BLOCKED - Prompt injection detected',
          onTrigger: {
            degrade: {
              toolsAllowlist: [],
              temperature: 0.2,
              durationSeconds: 20,
            },
          },
          enabled: true,
        },
      ],
    },
    metrics: {
      rateLimitTriggered: 0,
      inputCost: 0.0,
      outputCost: 0.0,
      guardrails: {
        value: 120,
        lastEvent:
        {
          routeName: 'marketing',
          name: 'Presidio',
          where: 'INPUT',
          type: 'PRESIDIO_ANALYZER',
          behavior: 'BLOCK',
          timestamp: '2025-10-14 12:58:00',
          apiKeyName: 'dev-team',
          apiKeyUuid: 'fbaa0880-1795-4d70-b073-cc92fc4498b7',
        },
      },
      totalInputTokenProcessed: 0,
      totalOutputTokenProcessed: 0,
      totalCost: 0.0,
    },
    groups: [],
  },
  {
    routeName: 'llm-judge-fallback-demo',
    configuration: {
      routeName: 'llm-judge-fallback-demo',
      chatModels: [
        {
          modelId: 'gpt-4o-mini',
          model: 'openai/gpt-4o-mini',
          credentials: {
            apiKey: '**********',
          },
          params: {
            temperature: 0.7,
            maxTokens: 500,
          },
          retryAttempts: 3,
          inputCostPerMillionTokens: 0.15,
          outputCostPerMillionTokens: 0.6,
          inputCostPerToken: 1.5e-07,
          outputCostPerToken: 6e-07,
        },
        {
          modelId: 'gpt-3.5-turbo',
          model: 'openai/gpt-3.5-turbo',
          credentials: {
            apiKey: '**********',
          },
          params: {
            temperature: 0.3,
            maxTokens: 300,
          },
          retryAttempts: 3,
          inputCostPerMillionTokens: 1.5,
          outputCostPerMillionTokens: 2.0,
          inputCostPerToken: 1.5e-06,
          outputCostPerToken: 2e-06,
        },
      ],
      rateLimiting: {
        algorithm: 'FIXED_WINDOW',
        windowSize: '60 seconds',
        maxRequests: 10,
      },
      fallback: [],
      guardrails: [
        {
          name: 'toxicity_judge_fallback',
          type: 'JUDGE',
          description: 'Toxic content detection with fallback to safer model',
          where: 'INPUT',
          behavior: 'FALLBACK',
          parameters: {
            type: 'JUDGE',
            judgeConfig: {
              promptRef: 'toxicity_check.md',
              modelId: 'gpt-3.5-turbo',
              credentials: {
                apiKey: '**********',
              },
              temperature: 0.7,
              maxTokens: 100,
              requirePass: true,
              fallbackModelId: 'gpt-3.5-turbo',
              fallbackCredentials: {
                apiKey: '**********',
              },
              fallbackParams: {
                temperature: 0.2,
                maxTokens: 50,
              },
              fallbackDurationSeconds: 20,
            },
          },
          responseMessage: '🚨🚨🚨 FALLBACK TRIGGERED! 🚨🚨🚨\n\n⚠️ CONTENT DETECTED AS NON-BUSINESS\n🔄 SWITCHING TO SAFE MODE\n🔒 Using conservative model: gpt-3.5-turbo\n\nThis request will be processed in SAFE MODE with limited capabilities.',
          enabled: true,
        },
        {
          name: 'business_context_judge_fallback',
          type: 'JUDGE',
          description: 'Business context validation with fallback to safer model',
          where: 'INPUT',
          behavior: 'FALLBACK',
          parameters: {
            type: 'JUDGE',
            judgeConfig: {
              promptRef: 'business_context_check.md',
              modelId: 'gpt-3.5-turbo',
              credentials: {
                apiKey: '**********',
              },
              temperature: 0.7,
              maxTokens: 150,
              requirePass: true,
              fallbackModelId: 'gpt-3.5-turbo',
              fallbackCredentials: {
                apiKey: '**********',
              },
              fallbackParams: {
                temperature: 0.2,
                maxTokens: 50,
              },
              fallbackDurationSeconds: 20,
            },
          },
          responseMessage: '🚨🚨🚨 FALLBACK TRIGGERED! 🚨🚨🚨\n\n⚠️ NON-BUSINESS CONTENT DETECTED\n🔄 SWITCHING TO SAFE MODE\n🔒 Using conservative model: gpt-3.5-turbo\n\nThis request will be processed in SAFE MODE with limited capabilities.',
          enabled: true,
        },
      ],
    },
    metrics: {
      rateLimitTriggered: 0,
      inputCost: 0.0,
      outputCost: 0.0,
      guardrails: {
        value: 120,
        lastEvent:
        {
          routeName: 'marketing',
          name: 'Presidio',
          where: 'INPUT',
          type: 'PRESIDIO_ANALYZER',
          behavior: 'BLOCK',
          timestamp: '2025-10-14 12:58:00',
          apiKeyName: 'dev-team',
          apiKeyUuid: 'fbaa0880-1795-4d70-b073-cc92fc4498b7',
        },
      },
      totalInputTokenProcessed: 0,
      totalOutputTokenProcessed: 0,
      totalCost: 0.0,
    },
    groups: [],
  },
  {
    routeName: 'no-weather-guardrails-demo',
    configuration: {
      routeName: 'no-weather-guardrails-demo',
      chatModels: [
        {
          modelId: 'gpt-4o-mini',
          model: 'openai/gpt-4o-mini',
          credentials: {
            apiKey: '**********',
          },
          params: {
            temperature: 0.7,
            maxTokens: 500,
          },
          retryAttempts: 3,
          inputCostPerMillionTokens: 0.15,
          outputCostPerMillionTokens: 0.6,
          inputCostPerToken: 1.5e-07,
          outputCostPerToken: 6e-07,
        },
      ],
      rateLimiting: {
        algorithm: 'FIXED_WINDOW',
        windowSize: '60 seconds',
        maxRequests: 10,
      },
      fallback: [],
      guardrails: [
        {
          name: 'weather_questions_blocker',
          type: 'CONTAINS',
          description: 'Blocks weather-related questions as they are not business relevant',
          where: 'INPUT',
          behavior: 'BLOCK',
          parameters: {
            type: 'CHECK',
            values: [
              'weather',
              'temperature',
              'rain',
              'sunny',
              'cloudy',
              'forecast',
              'climate',
              'meteorology',
              'storm',
              'snow',
              'wind',
              'humidity',
              'precipitation',
              'barometric',
              'atmospheric',
            ],
            ignore_case: false,
          },
          responseMessage: '🌤️ Weather questions are not allowed. Please ask business-related questions only.',
          enabled: true,
        },
        {
          name: 'business_hours_checker',
          type: 'REGEX',
          description: 'Checks if user is asking about business hours and provides helpful response',
          where: 'INPUT',
          behavior: 'SOFT_BLOCK',
          parameters: {
            type: 'CHECK',
            values: [
              '(?i)(business\\s+hours?|opening\\s+hours?|when\\s+are\\s+you\\s+open|what\\s+time\\s+do\\s+you\\s+open|closing\\s+time)',
            ],
            ignore_case: false,
          },
          responseMessage: '🕒 Business hours: Monday-Friday 9:00-18:00, Saturday 10:00-14:00. Closed on Sundays.',
          enabled: true,
        },
      ],
    },
    metrics: {
      rateLimitTriggered: 0,
      inputCost: 0.0,
      outputCost: 0.0,
      guardrails: {
        value: 120,
        lastEvent:
        {
          routeName: 'marketing',
          name: 'Presidio',
          where: 'INPUT',
          type: 'PRESIDIO_ANALYZER',
          behavior: 'BLOCK',
          timestamp: '2025-10-14 12:58:00',
          apiKeyName: 'dev-team',
          apiKeyUuid: 'fbaa0880-1795-4d70-b073-cc92fc4498b7',
        },
      },
      totalInputTokenProcessed: 0,
      totalOutputTokenProcessed: 0,
      totalCost: 0.0,
    },
    groups: [],
  },
  {
    routeName: 'semantic-cache-demo',
    configuration: {
      routeName: 'semantic-cache-demo',
      chatModels: [
        {
          modelId: 'llama3',
          model: 'openai/llama3.2:3b',
          credentials: {
            apiKey: '**********',
            baseUrl: 'http://host.docker.internal:11434/v1',
          },
          params: {
            temperature: 0.7,
            topP: 0.9,
          },
          retryAttempts: 3,
          prompt: 'You are a helpful assistant.',
          role: 'system',
        },
      ],
      embeddingModels: [
        {
          modelId: 'text-embedding-3-small',
          model: 'openai/text-embedding-3-small',
          credentials: {
            apiKey: '**********',
          },
          retryAttempts: 3,
          inputCostPerMillionTokens: 0.02,
          inputCostPerToken: 2e-08,
        },
      ],
      fallback: [],
      guardrails: [],
      caching: {
        enabled: true,
        type: 'semantic',
        ttl: 120,
        embedding_model_id: 'text-embedding-3-small',
        similarity_threshold: 0.85,
        distance_metric: 'cosine',
        dim: 1536,
      },
    },
    metrics: {
      cacheTriggered: 112,
      cacheSavedTokensInput: 5264,
      cacheSavedTokensOutput: 5491,
      savedAmountInput: 0.0,
      savedAmountOutput: 0.0,
      inputCost: 0.0,
      outputCost: 0.0,
      totalInputTokenProcessed: 664,
      totalOutputTokenProcessed: 171,
      totalCachedTokens: 10755,
      totalSavedAmount: 0.0,
      totalCost: 0.0,
    },
    groups: [
      {
        uuid: 'f3825543-6299-4dc5-ad2f-2324da25d2c8',
        name: 'first-group',
        createdAt: '2025-10-15 12:55:31.549183+00:00',
        updatedAt: '2025-10-15 12:55:31.549183+00:00',
      },
    ],
  },
];

const getEventsByRoute = {
  fallbacks: [
    {
      target: 'model-A',
      fallback: 'model-B',
      timestamp: '2025-10-14 12:58:00',
      apiKeyName: 'dev-team',
      apiKeyUuid: '00000000-0000-0000-0000-000000000000',
    },
  ],
  guardrails: [{
    name: 'Presidio',
    where: 'INPUT',
    type: 'PRESIDIO_ANALYZER',
    behavior: 'BLOCK',
    timestamp: '2025-10-14 12:58:00',
    apiKeyName: 'dev-team',
    apiKeyUuid: '00000000-0000-0000-0000-000000000000',
  },
  ],
  tokenInputLimit: [
    {
      timestamp: '2025-10-14 12:58:00',
      apiKeyName: 'dev-team',
      apiKeyUuid: '00000000-0000-0000-0000-000000000000',
    },
  ],
  tokenOutputLimit: [
    {
      timestamp: '2025-10-14 12:58:00',
      apiKeyName: 'dev-team',
      apiKeyUuid: '00000000-0000-0000-0000-000000000000',
    },
  ],
  cacheTriggered: [],
};

export { getAllRoutes, getEventsByRoute };
