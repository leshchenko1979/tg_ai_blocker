import pytest

from ...app.database import add_spam_example, get_spam_examples, remove_spam_example


@pytest.mark.asyncio
async def test_get_spam_examples_common(patched_db_conn, clean_db):
    """Test getting common spam examples (without admin_ids)"""
    async with clean_db.acquire() as conn:
        # Add test example
        example_data = {"text": "spam text", "score": 80}
        await add_spam_example(text=example_data["text"], score=example_data["score"])

        # Get examples without admin_ids
        result = await get_spam_examples()

        # Verify
        assert len(result) == 1
        assert result[0]["text"] == "spam text"
        assert result[0]["score"] == 80


@pytest.mark.asyncio
async def test_get_spam_examples_with_admin(patched_db_conn, clean_db):
    """Test getting both common and admin-specific spam examples"""
    async with clean_db.acquire() as conn:
        admin_id = 12345

        # First ensure admin exists in administrators table
        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, 'testadmin', 100)
            ON CONFLICT DO NOTHING
        """,
            admin_id,
        )

        # Add common example
        common_example = {"text": "common spam", "score": 80}
        await add_spam_example(
            text=common_example["text"], score=common_example["score"]
        )

        # Add user-specific example
        user_example = {"text": "user spam", "score": 90}
        await add_spam_example(
            text=user_example["text"], score=user_example["score"], admin_id=admin_id
        )

        # Get all examples for the admin
        result = await get_spam_examples([admin_id])

        # Verify
        assert len(result) == 2
        assert any(ex["text"] == "common spam" for ex in result)
        assert any(ex["text"] == "user spam" for ex in result)


@pytest.mark.asyncio
async def test_get_spam_examples_with_multiple_admins(patched_db_conn, clean_db):
    """Test getting spam examples from multiple admins"""
    async with clean_db.acquire() as conn:
        admin_ids = [12345, 67890]

        # Ensure admins exist in administrators table
        for admin_id in admin_ids:
            await conn.execute(
                """
                INSERT INTO administrators (admin_id, username, credits)
                VALUES ($1, 'testadmin', 100)
                ON CONFLICT DO NOTHING
            """,
                admin_id,
            )

        # Add common example
        common_example = {"text": "common spam", "score": 80}
        await add_spam_example(
            text=common_example["text"], score=common_example["score"]
        )

        # Add examples for each admin
        examples = [
            {"text": "admin1 spam", "score": 90, "admin_id": admin_ids[0]},
            {"text": "admin2 spam", "score": 85, "admin_id": admin_ids[1]},
        ]

        for example in examples:
            await add_spam_example(
                text=example["text"],
                score=example["score"],
                admin_id=example["admin_id"],
            )

        # Get examples for both admins
        result = await get_spam_examples(admin_ids)

        # Verify
        assert len(result) == 3  # Common example + 2 admin-specific examples
        assert any(ex["text"] == "common spam" for ex in result)
        assert any(ex["text"] == "admin1 spam" for ex in result)
        assert any(ex["text"] == "admin2 spam" for ex in result)


@pytest.mark.asyncio
async def test_add_spam_example_common(patched_db_conn, clean_db):
    """Test adding a common spam example"""
    async with clean_db.acquire() as conn:
        example_data = {
            "text": "Buy cheap products!",
            "score": 90,
            "name": "Spammer",
            "bio": "Professional marketer",
        }

        # Add example without admin_id
        result = await add_spam_example(
            text=example_data["text"],
            score=example_data["score"],
            name=example_data["name"],
            bio=example_data["bio"],
        )

        # Verify
        assert result is True

        # Check if example was added
        examples = await get_spam_examples()
        assert len(examples) == 1
        assert examples[0]["text"] == example_data["text"]
        assert examples[0]["score"] == example_data["score"]
        assert examples[0]["name"] == example_data["name"]
        assert examples[0]["bio"] == example_data["bio"]


@pytest.mark.asyncio
async def test_add_spam_example_user_specific(patched_db_conn, clean_db):
    """Test adding an admin-specific spam example"""
    async with clean_db.acquire() as conn:
        admin_id = 12345

        # First ensure admin exists in administrators table
        await conn.execute(
            """
            INSERT INTO administrators (admin_id, username, credits)
            VALUES ($1, 'testadmin', 100)
            ON CONFLICT DO NOTHING
        """,
            admin_id,
        )

        example_data = {
            "text": "Buy cheap products!",
            "score": 90,
            "name": "Spammer",
            "bio": "Professional marketer",
        }

        # Add example with admin_id
        result = await add_spam_example(
            text=example_data["text"],
            score=example_data["score"],
            name=example_data["name"],
            bio=example_data["bio"],
            admin_id=admin_id,
        )

        # Verify
        assert result is True

        # Check if example was added
        examples = await get_spam_examples([admin_id])
        assert len(examples) == 1
        assert examples[0]["text"] == example_data["text"]


@pytest.mark.asyncio
async def test_add_spam_example_duplicate(patched_db_conn, clean_db):
    """Test adding a duplicate spam example"""
    async with clean_db.acquire() as conn:
        example_data = {
            "text": "Buy cheap products!",
            "score": 90,
            "name": "Spammer",
        }

        # Add first example
        await add_spam_example(
            text=example_data["text"],
            score=example_data["score"],
            name=example_data["name"],
        )

        # Add duplicate with different score
        result = await add_spam_example(
            text=example_data["text"],
            score=95,
            name=example_data["name"],
        )

        # Verify old example was updated
        assert result is True
        examples = await get_spam_examples()
        assert len(examples) == 1
        assert examples[0]["score"] == 95


@pytest.mark.asyncio
async def test_remove_spam_example(patched_db_conn, clean_db):
    """Test removing a spam example"""
    async with clean_db.acquire() as conn:
        example_data = {
            "text": "Buy cheap products!",
            "score": 90,
        }

        # Add example
        await add_spam_example(
            text=example_data["text"],
            score=example_data["score"],
        )

        # Remove example
        result = await remove_spam_example(example_data["text"])

        # Verify
        assert result is True
        examples = await get_spam_examples()
        assert len(examples) == 0


@pytest.mark.asyncio
async def test_remove_spam_example_not_found(patched_db_conn, clean_db):
    """Test removing a non-existent spam example"""
    async with clean_db.acquire() as conn:
        # Try to remove non-existent example
        result = await remove_spam_example("nonexistent")

        # Verify
        assert result is False
