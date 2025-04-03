#!/usr/bin/env python
import asyncio
import os
import tempfile
from pathlib import Path

from app.config import Config
from app.logger import logger
from app.tool.r2_upload_tool import R2UploadTool


async def test_file_upload():
    """test upload local file to r2"""
    # create a temporary test file
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as temp:
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>R2 Upload Test</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                h1 { color: #333; }
                .container { border: 1px solid #ddd; padding: 20px; }
            </style>
        </head>
        <body>
            <h1>R2 Upload Test</h1>
            <div class="container">
                <p>This is a test file uploaded to Cloudflare R2.</p>
                <p>Upload time: <span id="time"></span></p>
            </div>
            <script>
                document.getElementById('time').textContent = new Date().toLocaleString();
            </script>
        </body>
        </html>
        """
        temp.write(html_content.encode("utf-8"))
        temp_path = temp.name

    try:
        # initialize r2 upload tool
        r2_tool = R2UploadTool()

        # test file upload
        logger.info(f"start uploading html file: {temp_path}")
        result = await r2_tool.execute(file_path=temp_path, directory="tests/html")

        if result.error:
            logger.error(f"file upload failed: {result.error}")
        else:
            logger.info(f"file upload success: {result.output}")

    finally:
        # clean up temporary file
        os.unlink(temp_path)
        logger.info(f"temporary file deleted: {temp_path}")


async def test_content_upload():
    """test upload html content to r2"""
    # prepare html game content
    game_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>简单HTML游戏</title>
        <style>
            #game-area {
                width: 300px;
                height: 300px;
                border: 2px solid black;
                position: relative;
            }
            #player {
                width: 20px;
                height: 20px;
                background-color: red;
                position: absolute;
                top: 140px;
                left: 140px;
            }
            #score {
                margin-top: 10px;
                font-weight: bold;
            }
        </style>
    </head>
    <body>
        <h1>方向键移动小方块</h1>
        <div id="game-area">
            <div id="player"></div>
        </div>
        <div id="score">分数: 0</div>

        <script>
            const player = document.getElementById('player');
            const scoreDisplay = document.getElementById('score');
            let score = 0;
            const step = 10;

            document.addEventListener('keydown', function(e) {
                let left = parseInt(player.style.left || '140px');
                let top = parseInt(player.style.top || '140px');

                switch(e.key) {
                    case 'ArrowUp':
                        top = Math.max(0, top - step);
                        break;
                    case 'ArrowDown':
                        top = Math.min(280, top + step);
                        break;
                    case 'ArrowLeft':
                        left = Math.max(0, left - step);
                        break;
                    case 'ArrowRight':
                        left = Math.min(280, left + step);
                        break;
                }

                player.style.left = left + 'px';
                player.style.top = top + 'px';

                score++;
                scoreDisplay.textContent = '分数: ' + score;
            });
        </script>
    </body>
    </html>
    """

    # initialize r2 upload tool
    r2_tool = R2UploadTool()

    # test content upload
    logger.info("start uploading html game content")
    result = await r2_tool.execute(
        content=game_html, file_name="simple-game.html", directory="games/simple-move"
    )

    if result.error:
        logger.error(f"content upload failed: {result.error}")
    else:
        logger.info(f"content upload success: {result.output}")


async def test_game_with_assets():
    """test upload html game with assets"""
    # create temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # create game file structure
        game_dir = Path(temp_dir) / "puzzle-game"
        game_dir.mkdir()
        (game_dir / "css").mkdir()
        (game_dir / "js").mkdir()
        (game_dir / "images").mkdir()

        # create css file
        css_content = """
        body { font-family: Arial, sans-serif; background-color: #f0f0f0; }
        .game-container { width: 400px; margin: 0 auto; text-align: center; }
        .puzzle { display: grid; grid-template-columns: repeat(3, 1fr); gap: 5px; margin: 20px 0; }
        .puzzle-piece { width: 100px; height: 100px; background-color: #3498db; color: white;
                      display: flex; align-items: center; justify-content: center;
                      font-size: 24px; cursor: pointer; }
        .controls { margin-top: 20px; }
        .btn { padding: 8px 16px; background-color: #2ecc71; color: white;
              border: none; cursor: pointer; margin: 0 5px; }
        .btn:hover { background-color: #27ae60; }
        """
        with open(game_dir / "css" / "style.css", "w") as f:
            f.write(css_content)

        # create js file
        js_content = """
        document.addEventListener('DOMContentLoaded', function() {
            const puzzlePieces = document.querySelectorAll('.puzzle-piece');
            const shuffleBtn = document.getElementById('shuffle');
            const numbers = [1, 2, 3, 4, 5, 6, 7, 8, ''];

            // initialize puzzle
            function initPuzzle() {
                puzzlePieces.forEach((piece, index) => {
                    piece.textContent = numbers[index];
                    piece.addEventListener('click', movePiece);
                });
            }

            // shuffle puzzle
            function shufflePuzzle() {
                for (let i = numbers.length - 1; i > 0; i--) {
                    const j = Math.floor(Math.random() * (i + 1));
                    [numbers[i], numbers[j]] = [numbers[j], numbers[i]];
                }
                updatePuzzle();
            }

            // update puzzle display
            function updatePuzzle() {
                puzzlePieces.forEach((piece, index) => {
                    piece.textContent = numbers[index];
                });
            }

            // move puzzle
            function movePiece() {
                const index = Array.from(puzzlePieces).indexOf(this);
                const emptyIndex = numbers.indexOf('');

                // check if can move
                if (
                    (index === emptyIndex - 1 && emptyIndex % 3 !== 0) || // left
                    (index === emptyIndex + 1 && index % 3 !== 0) ||      // right
                    index === emptyIndex - 3 ||                           // up
                    index === emptyIndex + 3                              // down
                ) {
                    // swap position
                    numbers[emptyIndex] = numbers[index];
                    numbers[index] = '';
                    updatePuzzle();

                    // check if complete
                    if (isComplete()) {
                        setTimeout(() => alert('恭喜你完成了拼图!'), 300);
                    }
                }
            }

            // check if complete
            function isComplete() {
                for (let i = 0; i < 8; i++) {
                    if (numbers[i] !== i + 1) return false;
                }
                return numbers[8] === '';
            }

            // initialize
            initPuzzle();
            shuffleBtn.addEventListener('click', shufflePuzzle);
            shufflePuzzle();
        });
        """
        with open(game_dir / "js" / "game.js", "w") as f:
            f.write(js_content)

        # create html file
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>数字拼图游戏</title>
            <link rel="stylesheet" href="css/style.css">
        </head>
        <body>
            <div class="game-container">
                <h1>数字拼图游戏</h1>
                <p>点击方块移动，将它们按1-8的顺序排列</p>

                <div class="puzzle">
                    <div class="puzzle-piece"></div>
                    <div class="puzzle-piece"></div>
                    <div class="puzzle-piece"></div>
                    <div class="puzzle-piece"></div>
                    <div class="puzzle-piece"></div>
                    <div class="puzzle-piece"></div>
                    <div class="puzzle-piece"></div>
                    <div class="puzzle-piece"></div>
                    <div class="puzzle-piece"></div>
                </div>

                <div class="controls">
                    <button id="shuffle" class="btn">重新打乱</button>
                </div>
            </div>

            <script src="js/game.js"></script>
        </body>
        </html>
        """
        with open(game_dir / "index.html", "w") as f:
            f.write(html_content)

        # create a simple image file
        with open(game_dir / "images" / "logo.txt", "w") as f:
            f.write("This is a placeholder for a real image file.")

        # upload all files
        r2_tool = R2UploadTool()

        # upload main html file
        logger.info("start uploading html game file")
        result = await r2_tool.execute(
            file_path=str(game_dir / "index.html"), directory="games/puzzle"
        )

        if result.error:
            logger.error(f"main html game file upload failed: {result.error}")
            return
        else:
            logger.info(f"main html game file upload success: {result.output}")

        # upload css file
        result = await r2_tool.execute(
            file_path=str(game_dir / "css" / "style.css"), directory="games/puzzle/css"
        )

        # upload js file
        result = await r2_tool.execute(
            file_path=str(game_dir / "js" / "game.js"), directory="games/puzzle/js"
        )

        # upload image file
        result = await r2_tool.execute(
            file_path=str(game_dir / "images" / "logo.txt"),
            directory="games/puzzle/images",
        )

        logger.info("all game files uploaded")


async def main():
    """run all tests"""
    logger.info("========== start r2 upload test ==========")
    config = Config()
    print
    # ensure r2 is configured
    try:
        r2_tool = R2UploadTool()
        if not all(
            [
                r2_tool.default_account_id,
                r2_tool.default_access_key_id,
                r2_tool.default_secret_access_key,
                r2_tool.default_bucket,
            ]
        ):
            logger.error(
                "r2 configuration is incomplete. please check the [r2] section in config/config.toml"
            )
            logger.info(
                "please update the following configuration items: account_id, access_key_id, secret_access_key, bucket"
            )
            return
    except Exception as e:
        logger.error(f"error initializing r2 upload tool: {str(e)}")
        return

    # run tests
    logger.info("test 1: upload html file")
    await test_file_upload()

    logger.info("test 2: upload html content")
    await test_content_upload()

    logger.info("test 3: upload html game with assets")
    await test_game_with_assets()

    logger.info("========== r2 upload test completed ==========")


if __name__ == "__main__":
    asyncio.run(main())
