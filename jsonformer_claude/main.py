import re
import anthropic
from typing import List, Union, Dict, Any
from termcolor import cprint
import json


class JsonformerClaude:
    value: Dict[str, Any] = {}
    last_anthropic_response: str | None = None
    last_anthropic_response_finished: bool = False
    last_anthropic_stream = None
    llm_request_count = 0

    def __init__(
        self,
        anthropic_client: anthropic.Client,
        json_schema: Dict[str, Any],
        prompt: str,
        debug: bool = False,
        **claude_args,
    ):
        self.json_schema = json_schema
        self.prompt = prompt
        self.generation_marker = "|GENERATION|"
        self.debug_on = debug
        self.anthropic_client = anthropic_client
        self.claude_args = claude_args

    def debug(self, caller: str, value: str, is_prompt: bool = False):
        if self.debug_on:
            if is_prompt:
                cprint(caller, "green", end=" ")
                cprint(value, "yellow")
                pass
            else:
                cprint(caller, "green", end=" ")
                cprint(value, "blue")

    async def generate_number(self) -> int:
        prompt = self.get_prompt()
        progress = self.get_progress()
        self.debug("[generate_number]", prompt, is_prompt=True)

        def extract_number(s: str):
            number_match = re.search(r"(\b\d+(\.\d+)?)(?=[^0-9\.])\b", s)
            return number_match.group(0) if number_match else None

        stream = self.last_anthropic_stream
        if not await self.prefix_matches(progress) or stream is None:
            self.debug("[generate_number]", "prompt doesn't match, getting new stream")
            stream = self.completion(prompt)
            generated_number = ""
            async for completion in stream:
                completion = completion[len(progress) :]
                generated_number = extract_number(completion)
                if generated_number:
                    break
        else:
            if self.last_anthropic_response_finished:
                self.debug(
                    "[generate_number]", "prompt matches, getting from last response"
                )
                generated_number = extract_number(
                    self.last_anthropic_response[len(progress) :]
                )
            else:
                stream = self.last_anthropic_stream
                async for completion in stream:
                    completion = completion[len(progress) :]
                    generated_number = extract_number(completion)
                    if generated_number:
                        break

        self.debug("[generate_number]", generated_number)

        # if it's a float, return a float, otherwise return an int
        if "." in generated_number:
            return float(generated_number)
        return int(generated_number)

    async def generate_boolean(self) -> bool:
        prompt = self.get_prompt()
        progress = self.get_progress()
        self.debug("[generate_boolean]", prompt, is_prompt=True)

        stream = self.last_anthropic_stream

        def extract_boolean(s: str):
            boolean_match = re.search(r"\btrue\b|\bfalse\b", s, re.IGNORECASE)
            return boolean_match.group(0) if boolean_match else None

        if not await self.prefix_matches(progress) or stream is None:
            self.debug("[generate_boolean]", "prompt doesn't match, getting new stream")
            stream = self.completion(prompt)
            generated_boolean = ""
            async for completion in stream:
                completion = completion[len(progress) :]
                generated_boolean = extract_boolean(completion)
                if generated_boolean:
                    break

        else:
            if self.last_anthropic_response_finished:
                self.debug(
                    "[generate_boolean]", "prompt matches, getting from last response"
                )
                completion = self.last_anthropic_response[len(progress) :]
                generated_boolean = extract_boolean(completion)
                if not generated_boolean:
                    self.debug(
                        "[generate_boolean]",
                        "prompt matches but last response doesn't have a boolean",
                    )
                    print(generated_boolean)
            else:
                stream = self.last_anthropic_stream
                async for completion in stream:
                    completion = completion[len(progress) :]
                    generated_boolean = extract_boolean(completion)
                    if generated_boolean:
                        break

        self.debug("[generate_boolean]", generated_boolean)
        return generated_boolean.lower() == "true"

    async def _completion(self, prompt: str):
        self.debug("[completion] hitting anthropic", prompt)
        self.last_anthropic_response_finished = False
        stream = await self.anthropic_client.acompletion_stream(
            prompt=prompt,
            stop_sequences=[anthropic.HUMAN_PROMPT],
            **self.claude_args,
        )
        self.llm_request_count += 1
        async for response in stream:
            self.last_anthropic_response = prompt + response["completion"]
            assistant_index = self.last_anthropic_response.find(anthropic.AI_PROMPT)
            if assistant_index > -1:
                self.last_anthropic_response = self.strip_json_spaces(
                    self.last_anthropic_response[
                        assistant_index + len(anthropic.AI_PROMPT) :
                    ]
                )
            yield self.last_anthropic_response
        self.last_anthropic_response_finished = True

    def completion(self, prompt: str):
        self.last_anthropic_stream = self._completion(prompt)
        return self.last_anthropic_stream

    async def prefix_matches(self, progress) -> bool:
        if self.last_anthropic_response is None:
            return False
        response = self.last_anthropic_response
        assert (
            len(progress) < len(response) or not self.last_anthropic_response_finished
        )
        while len(progress) >= len(response):
            await self.last_anthropic_stream.__anext__()
            response = self.last_anthropic_response

        self.debug("[prefix_matches]", progress, response)

        result = response.startswith(progress)
        self.debug("[prefix_matches]", result)
        return result

    async def generate_string(self) -> str:
        prompt = self.get_prompt() + '"'
        progress = self.get_progress() + '"'
        self.debug("[generate_string]", prompt, is_prompt=True)

        def extract_string(s: str):
            quote_index = s.find('"')
            if quote_index > -1 and s[quote_index - 1] != "\\":
                return s[:quote_index]
            return None

        stream = self.last_anthropic_stream
        if not await self.prefix_matches(progress) or stream is None:
            self.debug("[generate_string]", "prompt doesn't match, getting new stream")
            stream = self.completion(prompt)
            generated_string = ""
            async for completion in stream:
                completion = completion[len(progress) :]
                generated_string = extract_string(completion)
                if generated_string:
                    break
        else:
            if self.last_anthropic_response_finished:
                self.debug(
                    "[generate_string]", "prompt matches, getting from last response"
                )
                generated_string = extract_string(
                    self.last_anthropic_response[len(progress) :]
                )
            else:
                stream = self.last_anthropic_stream
                async for response in stream:
                    # subtract the progress
                    completion = response[len(progress) :]
                    generated_string = extract_string(completion)
                    if generated_string:
                        break

        self.debug("[generate_string]:", generated_string)
        return generated_string

    async def generate_object(
        self, properties: Dict[str, Any], obj: Dict[str, Any]
    ) -> Dict[str, Any]:
        for key, schema in properties.items():
            self.debug("[generate_object] generating value for", key)
            obj[key] = await self.generate_value(schema, obj, key)
        return obj

    async def generate_value(
        self,
        schema: Dict[str, Any],
        obj: Union[Dict[str, Any], List[Any]],
        key: Union[str, None] = None,
    ) -> Any:
        schema_type = schema["type"]
        if schema_type == "number":
            if key:
                obj[key] = self.generation_marker
            else:
                obj.append(self.generation_marker)
            return await self.generate_number()
        elif schema_type == "boolean":
            if key:
                obj[key] = self.generation_marker
            else:
                obj.append(self.generation_marker)
            return await self.generate_boolean()
        elif schema_type == "string":
            if key:
                obj[key] = self.generation_marker
            else:
                obj.append(self.generation_marker)
            return await self.generate_string()
        elif schema_type == "array":
            new_array = []
            obj[key] = new_array
            return await self.generate_array(schema["items"], new_array)
        elif schema_type == "object":
            new_obj = {}
            if key:
                obj[key] = new_obj
            else:
                obj.append(new_obj)
            return await self.generate_object(schema["properties"], new_obj)
        else:
            raise ValueError(f"Unsupported schema type: {schema_type}")

    async def generate_array(
        self, item_schema: Dict[str, Any], arr: List[Any]
    ) -> List[Any]:
        while True:
            if self.last_anthropic_response is None:
                # todo: below is untested since we do not support top level arrays yet
                stream = self.completion(self.get_prompt())
                async for response in stream:
                    completion = response[len(self.get_progress()) :]
                    if completion and completion[0] == ",":
                        self.last_anthropic_response = completion[1:]
                        break
            else:
                arr.append(self.generation_marker)
                progress = self.get_progress()
                arr.pop()
                progress = progress.rstrip(",")
                response = self.last_anthropic_response
                while len(progress) >= len(response):
                    await self.last_anthropic_stream.__anext__()
                    response = self.last_anthropic_response
                next_char = response[len(progress)]
                if next_char == "]":
                    return arr

            value = await self.generate_value(item_schema, arr)
            arr[-1] = value

    def strip_json_spaces(self, json_string: str) -> str:
        should_remove_spaces = True

        def is_unescaped_quote(index):
            return json_string[index] == '"' and (
                index < 1 or json_string[index - 1] != "\\"
            )

        index = 0
        while index < len(json_string):
            if is_unescaped_quote(index):
                should_remove_spaces = not should_remove_spaces
            elif json_string[index] in [" ", "\t", "\n"] and should_remove_spaces:
                json_string = json_string[:index] + json_string[index + 1 :]
                continue
            index += 1
        return json_string

    def get_progress(self):
        progress = json.dumps(self.value, separators=(",", ":"))
        gen_marker_index = progress.find(f'"{self.generation_marker}"')
        if gen_marker_index != -1:
            progress = progress[:gen_marker_index]
        else:
            raise ValueError("Failed to find generation marker")
        return self.strip_json_spaces(progress)

    def get_prompt(self):
        template = """{HUMAN}{prompt}\nOutput result in the following JSON schema format:\n{schema}{AI}{progress}"""
        progress = self.get_progress()
        prompt = template.format(
            prompt=self.prompt,
            schema=json.dumps(self.json_schema),
            progress=progress,
            HUMAN=anthropic.HUMAN_PROMPT,
            AI=anthropic.AI_PROMPT,
        )
        return prompt.rstrip()

    async def __call__(self) -> Dict[str, Any]:
        self.llm_request_count = 0
        self.value = {}
        generated_data = await self.generate_object(
            self.json_schema["properties"], self.value
        )
        return generated_data