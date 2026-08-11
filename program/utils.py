import matplotlib.pyplot as plt

def setup_axis_strong(ax, labelsize=11):
    """Унифицированная настройка стиля осей для всех графиков"""
    bg_color = "#fcf7f7"
    text_color = '#e0e0e0'  # ИЗМЕНЕНО: был '#222222', теперь светло-серый для видимости на темном фоне
    grid_color = '#aaaaaa'
    
    ax.set_facecolor(bg_color)
    for spine in ax.spines.values():
        spine.set_color('#555555')
        spine.set_linewidth(1.2)
        
    ax.tick_params(axis='both', which='major', labelsize=labelsize, colors=text_color, width=1.0, length=5)
    ax.xaxis.label.set_color(text_color)
    ax.yaxis.label.set_color(text_color)
    ax.xaxis.label.set_fontsize(labelsize + 1)
    ax.yaxis.label.set_fontsize(labelsize + 1)
    ax.title.set_color(text_color)
    ax.title.set_fontsize(labelsize + 2)
    ax.title.set_fontweight('bold')
    ax.grid(True, linestyle='--', alpha=0.5, color=grid_color, linewidth=0.7)