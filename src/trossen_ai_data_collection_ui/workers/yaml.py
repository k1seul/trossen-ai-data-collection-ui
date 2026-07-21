from PySide6.QtCore import QObject, QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


class YamlHighlighter(QSyntaxHighlighter):
    """
    A syntax highlighter for YAML content.

    This class highlights YAML keys, values, and comments with different
    text styles for better readability in a text editor.
    """

    def __init__(self, parent: QObject = None) -> None:
        """
        Initialize the YamlHighlighter with rules for highlighting YAML syntax.

        :param parent: The parent document where highlighting will be applied.
        """
        super().__init__(parent)  # Initialize the parent QSyntaxHighlighter.
        self.highlighting_rules: list[
            tuple[QRegularExpression, QTextCharFormat]
        ] = []  # Store highlighting rules.

        key_format = QTextCharFormat()  # Define the format for YAML keys.
        key_format.setForeground(QColor("blue"))  # Set keys to blue color.
        key_format.setFontWeight(QFont.Weight.Bold)  # Set keys to bold font.
        self.highlighting_rules.append(
            (QRegularExpression(r"^\s*[\w\-]+(?=\s*:)"), key_format)
        )  # Add rule for keys.

        value_format = QTextCharFormat()  # Define the format for YAML values.
        value_format.setForeground(QColor("darkgreen"))  # Set values to dark green color.
        self.highlighting_rules.append(
            (QRegularExpression(r":\s*.*"), value_format)
        )  # Add rule for values.

        comment_format = QTextCharFormat()  # Define the format for YAML comments.
        comment_format.setForeground(QColor("gray"))  # Set comments to gray color.
        comment_format.setFontItalic(True)  # Set comments to italic.
        self.highlighting_rules.append(
            (QRegularExpression(r"#.*"), comment_format)
        )  # Add rule for comments.

    def highlightBlock(self, text: str) -> None:
        """
        Apply syntax highlighting to a block of text.

        :param text: The text block to highlight.
        """
        for (
            pattern,
            fmt,
        ) in self.highlighting_rules:  # Loop through all highlighting rules.
            match_iterator = pattern.globalMatch(text)  # Find all matches in the text block.
            while match_iterator.hasNext():  # Iterate through all matches.
                match = match_iterator.next()  # Get the current match.
                self.setFormat(
                    match.capturedStart(), match.capturedLength(), fmt
                )  # Apply the corresponding format.
